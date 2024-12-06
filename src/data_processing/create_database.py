import pandas as pd
import sqlite3
from datetime import datetime
import os
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('../logs/database_creation.log'),
        logging.StreamHandler()
    ]
)

class MovieDatabase:
    def __init__(self, db_name='movie_database.db'):
        self.db_name = db_name
        self.conn = None
        self.cursor = None

    def connect(self):
        """Connect to the SQLite database"""
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.cursor = self.conn.cursor()
            logging.info(f"Connected to database: {self.db_name}")
        except Exception as e:
            logging.error(f"Error connecting to database: {str(e)}")
            raise

    def create_tables(self):
        """Create the necessary database tables"""
        try:
            # Movies table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS movies (
                    film_id TEXT PRIMARY KEY,
                    title TEXT,
                    year INTEGER,
                    url TEXT
                )
            ''')

            # Users table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY
                )
            ''')

            # User_movies table (for watched films)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_movies (
                    username TEXT,
                    film_id TEXT,
                    rating INTEGER,
                    liked BOOLEAN,
                    watched_date TEXT,
                    PRIMARY KEY (username, film_id),
                    FOREIGN KEY (username) REFERENCES users(username),
                    FOREIGN KEY (film_id) REFERENCES movies(film_id)
                )
            ''')

            # Lists table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS lists (
                    list_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    title TEXT,
                    url TEXT,
                    film_count INTEGER,
                    description TEXT,
                    FOREIGN KEY (username) REFERENCES users(username)
                )
            ''')

            self.conn.commit()
            logging.info("Database tables created successfully")
        except Exception as e:
            logging.error(f"Error creating tables: {str(e)}")
            raise

    def import_movie_data(self, csv_path):
        """Import movie data from CSV"""
        try:
            # Read CSV in chunks to handle large files
            chunk_size = 10000
            for chunk in pd.read_csv(csv_path, chunksize=chunk_size):
                # Process each chunk
                records = chunk.to_dict('records')
                self.cursor.executemany(
                    'INSERT OR REPLACE INTO movies (film_id, title, year, url) VALUES (?, ?, ?, ?)',
                    [(str(r.get('film_id', '')), 
                      r.get('title', ''),
                      r.get('year', None),
                      r.get('url', '')) for r in records]
                )
                self.conn.commit()
                logging.info(f"Processed {len(records)} movies")
        except Exception as e:
            logging.error(f"Error importing movie data: {str(e)}")
            raise

    def import_user_data(self, json_file):
        """Import user data from JSON file"""
        try:
            # Read JSON data
            df = pd.read_json(json_file)
            username = df['username'].iloc[0]

            # Insert user
            self.cursor.execute('INSERT OR REPLACE INTO users (username) VALUES (?)', (username,))

            # Process films
            for film in df['films']:
                self.cursor.execute('''
                    INSERT OR REPLACE INTO user_movies 
                    (username, film_id, rating, liked, watched_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    username,
                    str(film['film_id']),
                    film.get('rating'),
                    film.get('liked', False),
                    film.get('watched_date')
                ))

            # Process lists
            for lst in df['lists']:
                self.cursor.execute('''
                    INSERT OR REPLACE INTO lists 
                    (username, title, url, film_count, description)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    username,
                    lst.get('title'),
                    lst.get('url'),
                    lst.get('film_count', 0),
                    lst.get('description')
                ))

            self.conn.commit()
            logging.info(f"Imported data for user: {username}")
        except Exception as e:
            logging.error(f"Error importing user data: {str(e)}")
            raise

    def close(self):
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            logging.info("Database connection closed")

def main():
    # Initialize database
    db = MovieDatabase()
    db.connect()
    db.create_tables()

    try:
        # Import movie data from CSV
        movie_data_path = 'data/movie_data.csv'
        if os.path.exists(movie_data_path):
            logging.info("Importing movie data from CSV...")
            db.import_movie_data(movie_data_path)

        # Import user data from JSON files
        data_dir = 'data'
        for filename in os.listdir(data_dir):
            if filename.endswith('.json'):
                json_path = os.path.join(data_dir, filename)
                logging.info(f"Importing user data from {filename}...")
                db.import_user_data(json_path)

    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
