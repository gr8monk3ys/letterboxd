import os
from dotenv import load_dotenv
import agentql
from agentql.ext.playwright.sync_api import Page
from playwright.sync_api import sync_playwright
import parameters
import csv
import time
import random
import logging
from datetime import datetime

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('letterboxd_follower.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# AgentQL Queries
LOGIN_QUERY = """
{
    username_field
    password_field
    login_button
}
"""

NEXT_BUTTON_QUERY = """
{
    next_button
}
"""

class LetterboxdFollower:
    def __init__(self):
        self.followed_count = 0
        self.csv_writer = None
        self.setup_csv()

    def setup_csv(self):
        """Initialize CSV file for logging followed users"""
        file_exists = os.path.isfile(parameters.file_name)
        self.csv_file = open(parameters.file_name, 'a', newline='', encoding='utf-8')
        self.csv_writer = csv.writer(self.csv_file)
        if not file_exists:
            self.csv_writer.writerow(['Timestamp', 'Username', 'Status'])

    def random_delay(self):
        """Add random delay between actions to simulate human behavior"""
        delay = random.uniform(parameters.min_delay, parameters.max_delay)
        time.sleep(delay)

    def login(self, page: Page) -> bool:
        """Log in to Letterboxd account"""
        try:
            page.goto("https://letterboxd.com/sign-in/")
            
            # Use AgentQL to find login elements
            login_elements = page.query_elements(LOGIN_QUERY)
            
            # Fill in login details
            login_elements.username_field.type(parameters.username, delay=200)
            login_elements.password_field.type(parameters.password, delay=200)
            login_elements.login_button.click()

            # Wait for login to complete by checking for site header
            page.wait_for_selector(".site-header")
            logging.info("Successfully logged in to Letterboxd")
            
            # Navigate to the specific followers page and wait for it to load
            logging.info(f"Navigating to {parameters.base_url}")
            page.goto(parameters.base_url)
            page.wait_for_selector(".person-summary", timeout=10000)
            logging.info("Successfully loaded followers page")
            
            self.random_delay()
            return True

        except Exception as e:
            logging.error(f"Failed to login: {str(e)}")
            return False

    def follow_users(self, page: Page):
        """Follow users from the followers page"""
        try:
            current_page = 1
            consecutive_timeouts = 0
            while current_page <= parameters.till_page:
                if self.followed_count >= parameters.max_follows_per_session:
                    logging.info(f"Reached maximum follows limit ({parameters.max_follows_per_session})")
                    break
                    
                logging.info(f"Processing page {current_page}")

                try:
                    # Scroll to load all content
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    self.random_delay()

                    # Find all follow buttons using Playwright's selector with reduced timeout
                    follow_buttons = page.locator('a[data-recaptcha-action=follow]:not([style*="display: none"])')
                    try:
                        button_count = follow_buttons.count()
                        logging.info(f"Found {button_count} potential users to follow")
                    except Exception as e:
                        logging.warning(f"Error getting button count: {str(e)}")
                        button_count = 0
                    
                    if button_count == 0:
                        logging.info("No more users to follow on this page")
                        break
                    
                    # Process each follow button
                    for i in range(button_count):
                        if self.followed_count >= parameters.max_follows_per_session:
                            break

                        try:
                            button = follow_buttons.nth(i)
                            
                            try:
                                # Set timeout for text content
                                button_text = button.text_content(timeout=10000)
                                username = button_text.replace('Follow ', '') if button_text else 'Unknown User'
                            except Exception as e:
                                logging.warning(f"Timeout getting button text, skipping: {str(e)}")
                                consecutive_timeouts += 1
                                if consecutive_timeouts >= 2:
                                    break
                                continue
                            
                            if not username or username == 'Unknown User':
                                logging.warning("Skipping user due to missing username")
                                continue

                            logging.info(f"Attempting to follow user: {username}")

                            try:
                                # Set timeout for button actions
                                button.scroll_into_view_if_needed(timeout=10000)
                                self.random_delay()
                                button.click(timeout=10000)

                                # Log successful follow
                                self.followed_count += 1
                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                self.csv_writer.writerow([timestamp, username, 'Success'])
                                logging.info(f"Followed user: {username} ({self.followed_count}/{parameters.max_follows_per_session})")
                                consecutive_timeouts = 0  # Reset timeout counter on success
                            except Exception as e:
                                if "Timeout" in str(e):
                                    consecutive_timeouts += 1
                                    logging.warning(f"Timeout clicking button ({consecutive_timeouts} consecutive timeouts)")
                                    if consecutive_timeouts >= 2:
                                        break
                                else:
                                    logging.error(f"Error clicking button: {str(e)}")
                                continue
                            
                            # Add delay between follows
                            self.random_delay()

                        except Exception as e:
                            if "Timeout" in str(e):
                                consecutive_timeouts += 1
                                logging.warning(f"Timeout occurred ({consecutive_timeouts} consecutive timeouts)")
                                if consecutive_timeouts >= 2:
                                    logging.info("Multiple timeouts occurred, moving to next page")
                                    break
                            else:
                                logging.error(f"Error following user: {str(e)}")
                                if 'username' in locals():
                                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                    self.csv_writer.writerow([timestamp, username, 'Failed'])

                    # If we had multiple timeouts, move to next page
                    if consecutive_timeouts >= 2:
                        consecutive_timeouts = 0  # Reset counter
                        # Construct next page URL manually
                        next_url = f"{parameters.base_url}page/{current_page + 1}/"
                    else:
                        # Check for next page using AgentQL
                        try:
                            next_button = page.query_elements(NEXT_BUTTON_QUERY).next_button
                            if not next_button or current_page >= parameters.till_page:
                                logging.info("No more pages to process")
                                break
                            next_url = f"https://letterboxd.com{next_button.get_attribute('href')}"
                        except Exception as e:
                            logging.warning(f"Error getting next button, using manual URL: {str(e)}")
                            next_url = f"{parameters.base_url}page/{current_page + 1}/"

                    # Navigate to next page
                    logging.info(f"Moving to page {current_page + 1}")
                    try:
                        page.goto(next_url, timeout=10000)
                        page.wait_for_selector(".person-summary", timeout=10000)
                        current_page += 1
                        self.random_delay()
                    except Exception as e:
                        logging.warning(f"Error navigating to next page, trying to continue: {str(e)}")
                        current_page += 1
                        continue

                except Exception as e:
                    if "Timeout" in str(e):
                        logging.warning("Page-level timeout occurred, attempting to continue...")
                        current_page += 1
                        continue
                    else:
                        logging.error(f"Error processing page: {str(e)}")
                        break

        except Exception as e:
            logging.error(f"Error in follow process: {str(e)}")
        finally:
            self.csv_file.flush()

    def cleanup(self):
        """Clean up resources"""
        if self.csv_file:
            self.csv_file.close()

def main():
    follower = LetterboxdFollower()
    
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            page = agentql.wrap(browser.new_page())
            
            if follower.login(page):
                follower.follow_users(page)
            else:
                logging.error("Failed to start following process due to login failure")
                
            browser.close()
            
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
    finally:
        follower.cleanup()

if __name__ == "__main__":
    main()