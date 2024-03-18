from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
import parameters, csv, os.path, time

service = Service(executable_path="C:\\Users\\JoeG&M\\Downloads\\chromedriver-win64\\chromedriver.exe")
driver = webdriver.Chrome(service=service)

def sleep(seconds):
    time.sleep(seconds)

def login(username, password):
    driver.get("https://letterboxd.com/login")
    username_field = driver.find_element(By.ID, 'username or email field id')
    password_field = driver.find_element(By.ID, 'password field id')
    login_button = driver.find_element(By.ID, 'login button id')
    
    username_field.send_keys(username)
    password_field.send_keys(password)
    login_button.click()
    
    # Wait for the login to complete (can be adjusted as necessary)
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'element unique to logged in users'))
    )

def is_logged_in():
    driver.get("https://letterboxd.com/")
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'element unique to logged in users'))
        )
        return True
    except:
        return False

def follow():
    if not is_logged_in():
        login('gr8monk3ys', 'Scaturchio8')  # Update with your credentials
    
    driver.get("https://letterboxd.com/cinemonika/followers/")
    count = 0
    try:
        elements = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[data-recaptcha-action=follow]:not([style*="display: none"])'))
        )
        for el in elements:
            sleep(1.5)
            el.click()
            count += 1
            if count == 25:
                break

        next_button = driver.find_element(By.CSS_SELECTOR, 'a.next')
        if next_button:
            next_button.click()
            sleep(2)
    except Exception as e:
        print("An error occurred:", e)

follow()
if __name__ == "__main__":

    service = Service()
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Login
        driver.get('https://www.linkedin.com/login')
        driver.find_element('id', 'username').send_keys(parameters.linkedin_username)
        driver.find_element('id', 'password').send_keys(parameters.linkedin_password)
        driver.find_element('xpath', '//*[@type="submit"]').click()
        time.sleep(10)
        # CSV file loging
        file_name = parameters.file_name
        file_exists = os.path.isfile(file_name)
        writer = csv.writer(open(file_name, 'a'))
        if not file_exists: writer.writerow(['Connection Summary'])
        ignore_list = parameters.ignore_list
        if ignore_list:
            ignore_list = [i.strip() for i in ignore_list.split(',') if i]
        else:
            ignore_list = []
        # Search
        search_and_send_request(keywords=parameters.keywords, till_page=parameters.till_page, writer=writer,
                                ignore_list=ignore_list)
    except KeyboardInterrupt:
        print("\n\nINFO: User Canceled\n")
    except Exception as e:
        print('ERROR: Unable to run, error - %s' % (e))
    finally:
        # Close browser
        driver.quit()