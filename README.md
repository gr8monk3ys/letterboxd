# Letterboxd User Data Scraper

A Python-based tool for scraping and analyzing Letterboxd user data. This tool allows you to collect movie ratings, likes, and lists from Letterboxd users and store them in a SQLite database for analysis.

## Features

- Scrape user movie data from Letterboxd profiles
- Extract film details including ratings, likes, and watched dates
- Store data in a SQLite database for efficient querying
- Generate insights and visualizations about user's movie watching habits

## Project Structure

```
letterboxd-followers/
├── scrape_user_info.py      # Main scraping script
├── parameters.py            # Configuration settings
├── requirements.txt         # Project dependencies
└── data_processing/
    ├── create_database.py   # Database creation and schema
    ├── analyze_data.py      # Data analysis and visualization
    └── db_connect.py        # Database connection utilities
```

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/letterboxd-followers.git
cd letterboxd-followers
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy the parameters template and configure your settings:
```bash
cp parameters.py.example parameters.py
```

4. Edit `parameters.py` with your Letterboxd username and desired settings:
```python
username = 'your_username'  # Your Letterboxd username
till_page = 30             # Number of pages to scrape
min_delay = 2              # Minimum delay between requests
max_delay = 5              # Maximum delay between requests
```

## Usage

1. Create the database:
```bash
python data_processing/create_database.py
```

2. Run the scraper:
```bash
python scrape_user_info.py
```

3. Analyze the data:
```bash
python data_processing/analyze_data.py
```

## Data Analysis

The tool provides several types of analysis:

- Basic user statistics (total movies watched, rating distribution)
- Movies watched by year
- Highest rated movies
- Movie preferences over time
- Generated visualizations saved as PNG files

## Database Schema

The SQLite database consists of four main tables:

1. `movies`
   - film_id (PRIMARY KEY)
   - title
   - year
   - url

2. `users`
   - username (PRIMARY KEY)

3. `user_movies`
   - username
   - film_id
   - rating
   - liked
   - watched_date
   - PRIMARY KEY (username, film_id)

4. `lists`
   - list_id (PRIMARY KEY)
   - username
   - title
   - url
   - film_count
   - description

## Rate Limiting

The scraper implements rate limiting to avoid overwhelming Letterboxd's servers:
- Configurable delays between requests
- Random delay variation
- Automatic retry mechanism for failed requests

## Error Handling

- Comprehensive logging system
- Graceful handling of network errors
- Database transaction management
- Retry mechanism for API requests

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for educational purposes only. Please be respectful of Letterboxd's terms of service and rate limiting when using this scraper.
