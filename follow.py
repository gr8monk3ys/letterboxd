from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
import parameters, csv, os.path, time, random

def login(username, password):
    login_button = driver.find_element(By.CLASS_NAME, 'standalone-flow-button')
    
    username_field.send_keys(username)
    password_field.send_keys(password)
    login_button.click()

def follow(till_page, driver):
    for page in range(20, till_page + 1):
        url = "https://letterboxd.com/kurstboy/followers/page/" + str(page) + "/"
        driver.get(url)
        print(f'\nINFO: Checking followers on page {page}')
        html = driver.find_element(By.TAG_NAME, 'html')
        html.send_keys(Keys.END)
        time.sleep(3)
        elements = WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'a[data-recaptcha-action=follow]:not([style*="display: none"])')))
        # try:
        for el in elements:
            time.sleep(random.randint(2, 3))  # Simulate human-like interaction delays
            driver.execute_script("arguments[0].scrollIntoView();", el)
            driver.execute_script("arguments[0].click();", el)
            # el.click()
            time.sleep(1.5)
                # count += 1
                # print(f"{count} ) FOLLOWED: Successfully followed")
                # if count == 25:  # Limit to 25 follow actions to avoid being too aggressive
                #     print("INFO: Reached follow limit of 25 for this session.")
                #     return

            # next_button = driver.find_element(By.CSS_SELECTOR, 'a.next')
            # if next_button.is_displayed():
            #     next_button.click()
            #     time.sleep(random.randint(1, 4))
            #     page += 1
            # else:
            #     print("INFO: No more pages to navigate. Finished following.")
            #     break
        # except Exception as e:
        #     print(f"An error occurred on page {page}: {e}")
        #     break

if __name__ == "__main__":

    service = Service()
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get("https://letterboxd.com/sign-in/")
        username_field = driver.find_element(By.ID, 'field-username')
        password_field = driver.find_element(By.ID, 'field-password')
        login(parameters.username, parameters.password)
        time.sleep(2)

        # CSV file loging
        # file_name = parameters.file_name
        # file_exists = os.path.isfile(file_name)
        # writer = csv.writer(open(file_name, 'a'))
        # if not file_exists: writer.writerow(['Connection Summary'])
        follow(parameters.till_page, driver)
    except KeyboardInterrupt:
        print("\n\nINFO: User Canceled\n")
    except Exception as e:
        print('ERROR: Unable to run, error - %s' % (e))
    finally:
        # Close browser
        driver.quit()