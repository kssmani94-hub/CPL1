import pandas as pd
from app import app, db
from models import Player, Team
import math # Import math for isnan check

def import_players_from_csv(filepath='players_data.csv'):
    """Reads player data from CSV and populates the database."""
    try:
        # Read CSV, ensure empty strings are read as NaN for consistency
        df = pd.read_csv(filepath).fillna(value=pd.NA)
        print(f"Reading data from {filepath}...")
    except FileNotFoundError:
        print(f"Error: CSV file not found at {filepath}")
        return
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return

    # Get existing teams to map names to IDs
    with app.app_context(): # Need app context to query DB
        teams_map = {team.team_name.strip(): team.id for team in Team.query.all()} # Strip whitespace from names

    new_players_count = 0
    updated_players_count = 0

    with app.app_context(): # Need app context to interact with DB
        for index, row in df.iterrows():
            try:
                player_name = str(row['player_name']).strip() if pd.notna(row['player_name']) else None
                if not player_name:
                    print(f"Skipping row {index + 2}: Missing player name.")
                    continue

                player = Player.query.filter_by(player_name=player_name).first()

                # Handle boolean conversion robustly
                is_retained_val = row.get('is_retained', False)
                is_retained = str(is_retained_val).strip().upper() in ['TRUE', '1', 'YES', 'T']

                retaining_team_name = str(row.get('retaining_team_name', '')).strip() if pd.notna(row.get('retaining_team_name')) else ''
                last_year_price_val = row.get('last_year_price', 0)
                # Handle potential NaN or empty strings before converting to int
                last_year_price = int(float(last_year_price_val)) if pd.notna(last_year_price_val) and str(last_year_price_val).strip() else 0


                team_id = None
                if is_retained and retaining_team_name:
                    if retaining_team_name in teams_map:
                        team_id = teams_map[retaining_team_name]
                    else:
                        print(f"Warning: Retaining team '{retaining_team_name}' not found for player '{player_name}'. Skipping retention assignment.")
                        is_retained = False # Cannot retain without valid team

                # Handle potential missing image filename
                image_filename = str(row.get('image_filename')).strip() if pd.notna(row.get('image_filename')) else None


                # Function to safely convert to int, handling NA/NaN/empty
                def safe_int(value, default=0):
                    if pd.isna(value) or (isinstance(value, str) and not value.strip()): return default
                    try: return int(float(value)) # Convert to float first to handle '10.0' etc.
                    except (ValueError, TypeError): return default

                # Function to safely convert to float, handling NA/NaN/empty
                def safe_float(value, default=0.0):
                    if pd.isna(value) or (isinstance(value, str) and not value.strip()): return default
                    try: return float(value)
                    except (ValueError, TypeError): return default

                if not player:
                    # Create new player
                    player = Player(
                        player_name=player_name,
                        image_filename=image_filename if image_filename else 'default_player.png', # Use default if blank
                        is_retained=is_retained,
                        team_id=team_id,
                        sold_price=last_year_price if is_retained else 0,
                        status='Retained' if is_retained else 'Unsold',
                        # --- Fill in ALL other stats safely ---
                        cpl_2024_team=str(row.get('cpl_2024_team')).strip() if pd.notna(row.get('cpl_2024_team')) else None,
                        cpl_2024_innings=safe_int(row.get('cpl_2024_innings')),
                        cpl_2024_runs=safe_int(row.get('cpl_2024_runs')),
                        cpl_2024_average=safe_float(row.get('cpl_2024_average')),
                        cpl_2024_sr=safe_float(row.get('cpl_2024_sr')),
                        cpl_2024_hs=safe_int(row.get('cpl_2024_hs')),
                        overall_matches=safe_int(row.get('overall_matches')),
                        overall_runs=safe_int(row.get('overall_runs')),
                        overall_wickets=safe_int(row.get('overall_wickets')),
                        overall_bat_avg=safe_float(row.get('overall_bat_avg')),
                        overall_bowl_avg=safe_float(row.get('overall_bowl_avg'))
                    )
                    db.session.add(player)
                    new_players_count += 1
                else:
                    # Update existing player's retention details
                    print(f"Player '{player_name}' already exists. Updating retention status/price/team if specified.")
                    player.is_retained = is_retained
                    player.team_id = team_id # This will be None if not retained or team not found
                    player.sold_price = last_year_price if is_retained else 0 # Reset price if not retained
                    player.image_filename = image_filename if image_filename else player.image_filename # Update image if provided

                    # Update status based on retention, but don't override 'Sold'
                    if is_retained and player.status != 'Sold':
                        player.status = 'Retained'
                    elif not is_retained and player.status == 'Retained': # If changed FROM retained TO auction
                        player.status = 'Unsold'

                    # Optionally update stats for existing players too
                    # player.cpl_2024_innings = safe_int(row.get('cpl_2024_innings', player.cpl_2024_innings))
                    # ... etc for other stats ...

                    updated_players_count += 1
            except Exception as e:
                print(f"Error processing row {index + 2} for player '{row.get('player_name', 'N/A')}': {e}")
                db.session.rollback() # Rollback changes for this row

        try:
            db.session.commit()
            print(f"Import complete. Added: {new_players_count}, Updated: {updated_players_count}")
        except Exception as e:
            db.session.rollback()
            print(f"Error during final database commit: {e}")

    # --- Recalculate initial team stats after import ---
    recalculate_initial_team_stats()


def recalculate_initial_team_stats():
    """Calculates team stats based on retained players."""
    print("Recalculating initial team stats based on retained players...")
    with app.app_context():
        all_teams = Team.query.all()
        max_slots = 15 # Define max slots per team

        for team in all_teams:
            # Query retained players dynamically for the team
            retained_players = team.players.filter_by(is_retained=True).all()
            retained_count = len(retained_players)
            # Sum of last year's prices (stored in sold_price for retained players)
            retained_cost = sum(p.sold_price for p in retained_players if p.sold_price is not None)

            team.players_taken_count = retained_count
            team.slots_remaining = max_slots - retained_count
            team.purse_spent = retained_cost
            team.purse = 10000 - retained_cost # Assuming total 10000 purse

            print(f"Team: {team.team_name}, Retained: {retained_count}, Cost: {retained_cost}, Purse Left: {team.purse}, Slots Left: {team.slots_remaining}")


        try:
            db.session.commit()
            print("Initial team stats updated successfully.")
        except Exception as e:
            db.session.rollback()
            print(f"Error updating team stats: {e}")


if __name__ == '__main__':
    # Ensure tables exist before running import
    with app.app_context():
        inspector = db.inspect(db.engine)
        if not inspector.has_table("player") or not inspector.has_table("team"):
            print("Database tables ('player' or 'team') not found.")
            print("Please run the Flask app once (`flask run`) to create the database and tables before importing.")
        else:
            # Clear existing players before import if you want a fresh start each time
            # print("Deleting existing players...")
            # Player.query.delete()
            # db.session.commit()
            # print("Existing players deleted.")

            # Proceed with import
            import_players_from_csv()