import json
import os
from openai import OpenAI
import time
from dotenv import load_dotenv
import logging
from tqdm import tqdm

# Set up logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('logs', 'review_generation.log')),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

class ReviewGenerator:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.review_prompt_template = """
        Write a thoughtful and engaging Letterboxd-style review for the movie with ID {film_id} from {year}. 
        The review should:
        - Be between 100-150 words
        - Have a casual, personal tone typical of Letterboxd
        - Include specific observations about the film's strengths or weaknesses
        - Mention notable aspects of directing, acting, or cinematography
        - End with a brief overall assessment
        - Avoid major spoilers
        """

    def generate_review(self, movie):
        """Generate a review for a single movie using GPT-3.5"""
        try:
            prompt = self.review_prompt_template.format(
                film_id=movie.get('film_id', 'Unknown'),
                year=movie.get('year', 'Unknown')
            )

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a film enthusiast writing reviews on Letterboxd."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=200
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logging.error(f"Error generating review for film ID {movie.get('film_id')}: {str(e)}")
            return None

    def process_movies(self, input_file, output_file):
        """Process all movies in the input file and generate reviews"""
        try:
            # Load the movie data
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Get the films array
            films = data.get('films', [])
            total_movies = len(films)
            logging.info(f"Starting review generation for {total_movies} movies")

            # Process each movie
            for movie in tqdm(films, desc="Generating reviews"):
                if 'ai_review' not in movie:  # Skip if review already exists
                    review = self.generate_review(movie)
                    if review:
                        movie['ai_review'] = review
                        # Save after each successful review to prevent data loss
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    # Add delay to respect API rate limits
                    time.sleep(1)

            logging.info("Review generation completed successfully")
            return True

        except Exception as e:
            logging.error(f"Error processing movies: {str(e)}")
            return False

def main():
    # File paths
    input_file = 'data/gr8monk3ys_20241204_080010.json'
    output_file = 'data/gr8monk3ys_with_reviews.json'

    # Create ReviewGenerator instance
    generator = ReviewGenerator()

    # Process the movies
    success = generator.process_movies(input_file, output_file)
    
    if success:
        print("Successfully generated reviews and saved to", output_file)
    else:
        print("Error occurred during review generation. Check the logs for details.")

if __name__ == "__main__":
    main()
