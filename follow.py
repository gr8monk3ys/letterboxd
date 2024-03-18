from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
import parameters, csv, os.path, time, random

service = Service(executable_path="C:\\Users\\JoeG&M\\Downloads\\chromedriver-win64\\chromedriver.exe")
driver = webdriver.Chrome(service=service)

def sleep(seconds):
    time.sleep(seconds)

def login(username, password):
    login_button = driver.find_element(By.CLASS_NAME, 'standalone-flow-button')
    
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
    driver.get("https://letterboxd.com/kurstboy/followers/")
    count = 0
    try:
        elements = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'ajax-click-action button'))
        )
        for el in elements:
            sleep(random.randint(1, 2))
            el.click()
            count += 1
            if count == 25:
                break

        next_button = driver.find_element(By.CLASS_NAME, 'next')
        if next_button:
            next_button.click()
            time.sleep(random.randint(1, 4))
    except Exception as e:
        print("An error occurred:", e)

follow()
if __name__ == "__main__":

    service = Service()
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get("https://letterboxd.com/sign-in/")
        username_field = driver.find_element(By.ID, 'field-username')
        password_field = driver.find_element(By.ID, 'field-password')
        login(username_field, password_field)
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
        follow()
    except KeyboardInterrupt:
        print("\n\nINFO: User Canceled\n")
    except Exception as e:
        print('ERROR: Unable to run, error - %s' % (e))
    finally:
        # Close browser
        driver.quit()