import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_analysis.log'),
        logging.StreamHandler()
    ]
)

class MovieAnalyzer:
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

    def get_user_stats(self, username):
        """Get basic statistics for a user"""
        try:
            # Total movies watched
            self.cursor.execute('''
                SELECT COUNT(*) FROM user_movies WHERE username = ?
            ''', (username,))
            total_movies = self.cursor.fetchone()[0]

            # Movies with ratings
            self.cursor.execute('''
                SELECT COUNT(*) FROM user_movies 
                WHERE username = ? AND rating IS NOT NULL
            ''', (username,))
            rated_movies = self.cursor.fetchone()[0]

            # Liked movies
            self.cursor.execute('''
                SELECT COUNT(*) FROM user_movies 
                WHERE username = ? AND liked = 1
            ''', (username,))
            liked_movies = self.cursor.fetchone()[0]

            # Number of lists
            self.cursor.execute('''
                SELECT COUNT(*) FROM lists WHERE username = ?
            ''', (username,))
            num_lists = self.cursor.fetchone()[0]

            # Average rating
            self.cursor.execute('''
                SELECT AVG(rating) FROM user_movies 
                WHERE username = ? AND rating IS NOT NULL
            ''', (username,))
            avg_rating = self.cursor.fetchone()[0]

            return {
                'total_movies': total_movies,
                'rated_movies': rated_movies,
                'liked_movies': liked_movies,
                'num_lists': num_lists,
                'avg_rating': round(avg_rating, 2) if avg_rating else None
            }
        except Exception as e:
            logging.error(f"Error getting user stats: {str(e)}")
            return None

    def get_movies_by_year(self, username):
        """Get distribution of movies by year"""
        try:
            query = '''
                SELECT m.year, COUNT(*) as count
                FROM user_movies um
                JOIN movies m ON um.film_id = m.film_id
                WHERE um.username = ? AND m.year IS NOT NULL
                GROUP BY m.year
                ORDER BY m.year
            '''
            df = pd.read_sql_query(query, self.conn, params=(username,))
            return df
        except Exception as e:
            logging.error(f"Error getting movies by year: {str(e)}")
            return None

    def get_rating_distribution(self, username):
        """Get distribution of ratings"""
        try:
            query = '''
                SELECT rating, COUNT(*) as count
                FROM user_movies
                WHERE username = ? AND rating IS NOT NULL
                GROUP BY rating
                ORDER BY rating
            '''
            df = pd.read_sql_query(query, self.conn, params=(username,))
            return df
        except Exception as e:
            logging.error(f"Error getting rating distribution: {str(e)}")
            return None

    def plot_movies_by_year(self, username):
        """Plot movies watched by year"""
        try:
            df = self.get_movies_by_year(username)
            if df is not None and not df.empty:
                plt.figure(figsize=(15, 6))
                plt.bar(df['year'], df['count'])
                plt.title(f'Movies Watched by Year - {username}')
                plt.xlabel('Year')
                plt.ylabel('Number of Movies')
                plt.xticks(rotation=45)
                plt.tight_layout()
                plt.savefig(f'movies_by_year_{username}.png')
                plt.close()
                logging.info(f"Created movies by year plot for {username}")
        except Exception as e:
            logging.error(f"Error plotting movies by year: {str(e)}")

    def plot_rating_distribution(self, username):
        """Plot rating distribution"""
        try:
            df = self.get_rating_distribution(username)
            if df is not None and not df.empty:
                plt.figure(figsize=(10, 6))
                plt.bar(df['rating'], df['count'])
                plt.title(f'Rating Distribution - {username}')
                plt.xlabel('Rating')
                plt.ylabel('Number of Movies')
                plt.tight_layout()
                plt.savefig(f'rating_distribution_{username}.png')
                plt.close()
                logging.info(f"Created rating distribution plot for {username}")
        except Exception as e:
            logging.error(f"Error plotting rating distribution: {str(e)}")

    def get_most_watched_years(self, username, top_n=10):
        """Get the most watched years"""
        try:
            query = '''
                SELECT m.year, COUNT(*) as count
                FROM user_movies um
                JOIN movies m ON um.film_id = m.film_id
                WHERE um.username = ? AND m.year IS NOT NULL
                GROUP BY m.year
                ORDER BY count DESC
                LIMIT ?
            '''
            df = pd.read_sql_query(query, self.conn, params=(username, top_n))
            return df
        except Exception as e:
            logging.error(f"Error getting most watched years: {str(e)}")
            return None

    def get_highest_rated_movies(self, username, top_n=10):
        """Get highest rated movies"""
        try:
            query = '''
                SELECT m.title, m.year, um.rating
                FROM user_movies um
                JOIN movies m ON um.film_id = m.film_id
                WHERE um.username = ? AND um.rating IS NOT NULL
                ORDER BY um.rating DESC
                LIMIT ?
            '''
            df = pd.read_sql_query(query, self.conn, params=(username, top_n))
            return df
        except Exception as e:
            logging.error(f"Error getting highest rated movies: {str(e)}")
            return None

    def analyze_user(self, username):
        """Perform comprehensive analysis for a user"""
        logging.info(f"Starting analysis for user: {username}")

        # Get basic stats
        stats = self.get_user_stats(username)
        if stats:
            print(f"\nUser Statistics for {username}:")
            print(f"Total Movies Watched: {stats['total_movies']}")
            print(f"Movies Rated: {stats['rated_movies']}")
            print(f"Movies Liked: {stats['liked_movies']}")
            print(f"Number of Lists: {stats['num_lists']}")
            print(f"Average Rating: {stats['avg_rating']}")

        # Get most watched years
        top_years = self.get_most_watched_years(username)
        if top_years is not None and not top_years.empty:
            print("\nMost Watched Years:")
            print(top_years)

        # Get highest rated movies
        top_movies = self.get_highest_rated_movies(username)
        if top_movies is not None and not top_movies.empty:
            print("\nHighest Rated Movies:")
            print(top_movies)

        # Create visualizations
        self.plot_movies_by_year(username)
        self.plot_rating_distribution(username)

    def close(self):
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            logging.info("Database connection closed")

def main():
    analyzer = MovieAnalyzer()
    analyzer.connect()

    try:
        # Get list of users
        analyzer.cursor.execute('SELECT username FROM users')
        users = [row[0] for row in analyzer.cursor.fetchall()]

        for username in users:
            analyzer.analyze_user(username)

    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}")
    finally:
        analyzer.close()

if __name__ == "__main__":
    main()
