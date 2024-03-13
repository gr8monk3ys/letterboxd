import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

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

# Example use
follow()
# driver.quit()