import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import pandas as pd
import logging
from bs4 import BeautifulSoup
import json
from datetime import datetime
import parameters
import requests

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('letterboxd_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class LetterboxdUserScraper:
    def __init__(self):
        self.username = parameters.username
        self.base_url = "https://letterboxd.com"
        self.user_data = {
            'username': self.username,
            'films': [],
            'ratings': [],
            'likes': [],
            'lists': []
        }
        self.min_delay = parameters.min_delay
        self.max_delay = parameters.max_delay
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        }

    def get_film_title(self, film_id):
        """Get film title from Letterboxd API"""
        try:
            url = f"https://letterboxd.com/ajax/film/{film_id}/stats/"
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                data = response.json()
                return data.get('film', {}).get('title')
            return None
        except Exception as e:
            logging.error(f"Error getting film title for ID {film_id}: {str(e)}")
            return None

    def get_page_count(self, page, section='films'):
        """Get the total number of pages for a given section"""
        try:
            page.goto(f"{self.base_url}/{self.username}/{section}/")
            page.wait_for_load_state('networkidle')
            
            # Find pagination
            last_page = page.query_selector('li.paginate-page:last-child')
            if last_page:
                return int(last_page.inner_text())
            return 1
        except Exception as e:
            logging.error(f"Error getting page count for {section}: {str(e)}")
            return 0

    def scrape_films(self, page, include_ratings=True):
        """Scrape user's watched films and ratings"""
        try:
            logging.info(f"Scraping films for user: {self.username}")
            
            # Get total pages
            total_pages = self.get_page_count(page, 'films')
            if parameters.till_page:
                total_pages = min(total_pages, parameters.till_page)
            logging.info(f"Found {total_pages} pages of films")

            for page_num in range(1, total_pages + 1):
                url = f"{self.base_url}/{self.username}/films/page/{page_num}"
                page.goto(url)
                page.wait_for_load_state('networkidle')

                # Use JavaScript to extract film data
                films_data = page.evaluate("""
                    () => {
                        const films = [];
                        document.querySelectorAll('li.poster-container').forEach(container => {
                            const poster = container.querySelector('.film-poster');
                            if (poster) {
                                films.push({
                                    film_id: poster.getAttribute('data-film-id'),
                                    year: poster.getAttribute('data-film-release-year'),
                                    rating: poster.getAttribute('data-rating'),
                                    liked: poster.getAttribute('data-liked') === 'true',
                                    watched_date: poster.getAttribute('data-viewing-date'),
                                    url: `https://letterboxd.com/film/${poster.getAttribute('data-film-slug')}`
                                });
                            }
                        });
                        return films;
                    }
                """)
                
                for film in films_data:
                    film['title'] = self.get_film_title(film['film_id'])
                    self.user_data['films'].append(film)
                    if film['rating']:
                        self.user_data['ratings'].append(film)
                    if film['liked']:
                        self.user_data['likes'].append(film)

                logging.info(f"Processed page {page_num}/{total_pages}")
                time.sleep(self.min_delay + (self.max_delay - self.min_delay) * (page_num / total_pages))

            logging.info(f"Scraped {len(self.user_data['films'])} films total")
            
        except Exception as e:
            logging.error(f"Error scraping films: {str(e)}")

    def scrape_lists(self, page):
        """Scrape user's lists"""
        try:
            logging.info(f"Scraping lists for user: {self.username}")
            page.goto(f"{self.base_url}/{self.username}/lists/")
            page.wait_for_load_state('networkidle')

            # Use JavaScript to extract list data
            lists_data = page.evaluate("""
                () => {
                    const lists = [];
                    document.querySelectorAll('.list-link').forEach(item => {
                        const title = item.querySelector('h2.title')?.innerText;
                        const count = item.querySelector('.list-count')?.innerText;
                        const desc = item.querySelector('.list-description')?.innerText;
                        lists.push({
                            title: title || null,
                            url: item.href,
                            film_count: count || "0",
                            description: desc || null
                        });
                    });
                    return lists;
                }
            """)
            
            self.user_data['lists'] = lists_data
            logging.info(f"Scraped {len(self.user_data['lists'])} lists")
            
        except Exception as e:
            logging.error(f"Error scraping lists: {str(e)}")

    def save_data(self):
        """Save the scraped data to JSON and CSV files"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            os.makedirs('data', exist_ok=True)
            
            # Save all data to JSON
            json_file = f'data/{self.username}_{timestamp}.json'
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_data, f, indent=2, ensure_ascii=False)
            
            # Save films to CSV
            films_df = pd.DataFrame(self.user_data['films'])
            films_df.to_csv(f'data/{self.username}_films_{timestamp}.csv', index=False, encoding='utf-8')
            
            # Save ratings to CSV
            if self.user_data['ratings']:
                ratings_df = pd.DataFrame(self.user_data['ratings'])
                ratings_df.to_csv(f'data/{self.username}_ratings_{timestamp}.csv', index=False, encoding='utf-8')
            
            # Save likes to CSV
            if self.user_data['likes']:
                likes_df = pd.DataFrame(self.user_data['likes'])
                likes_df.to_csv(f'data/{self.username}_likes_{timestamp}.csv', index=False, encoding='utf-8')
            
            # Save lists to CSV
            if self.user_data['lists']:
                lists_df = pd.DataFrame(self.user_data['lists'])
                lists_df.to_csv(f'data/{self.username}_lists_{timestamp}.csv', index=False, encoding='utf-8')
            
            logging.info(f"Data saved to files with timestamp {timestamp}")
            
        except Exception as e:
            logging.error(f"Error saving data: {str(e)}")

    def scrape_user_data(self, page):
        """Main method to scrape all user data"""
        self.scrape_films(page)
        self.scrape_lists(page)

    def run(self):
        """Run the scraping process"""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            
            try:
                self.scrape_user_data(page)
                self.save_data()
            except Exception as e:
                logging.error(f"Error during scraping: {str(e)}")
            finally:
                browser.close()

if __name__ == "__main__":
    scraper = LetterboxdUserScraper()
    scraper.run()
