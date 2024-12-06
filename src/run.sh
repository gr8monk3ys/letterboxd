echo "Initializing the database..."
pip install poetry
python -m poetry install
python -m poetry run python data_processing/scrape_user_info.py

echo "Following users..."
python -m poetry run python following/follow_users.py

echo "Creating reviews..."
python -m poetry run python reviewing/write_review.py