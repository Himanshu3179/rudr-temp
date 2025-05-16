import asyncio
from playwright.async_api import async_playwright, TimeoutError
import json
import re
import os # For file operations (checking existence, renaming, deleting)
from datetime import datetime # For timestamping save operations

# --- Configuration Constants ---
OUTPUT_FILENAME = "apniroots_products.json"
TEMP_SAVE_FILENAME = "apniroots_products_partial.json"
SCROLL_PAUSE_TIME = 1.0 # Time to wait after scroll for content to appear (in seconds)
NETWORK_IDLE_TIMEOUT = 10000 # Timeout for networkidle state (in milliseconds)
MAX_NO_CHANGE_SCROLLS = 5 # How many times we tolerate no new content before stopping
SAVE_INTERVAL_PRODUCTS = 20 # Save data after every X new products scraped

async def load_previous_data(filename):
    """Loads previously scraped data from a JSON file."""
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                print(f"Loading previous data from {filename}...")
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {filename}. Starting fresh.")
            return []
    return []

async def save_partial_data(data, filename):
    """Saves partial scraped data to a JSON file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved partial data to {filename}. Total items: {len(data)}")
    except IOError as e:
        print(f"Error saving partial data to {filename}: {e}")

def parse_price(price_str):
    """Parses a price string and converts it to a float."""
    if not price_str:
        return None
    # Remove currency symbols, commas, and any non-numeric characters except the decimal point
    cleaned_price = re.sub(r'[^\d.]', '', price_str)
    try:
        return float(cleaned_price)
    except ValueError:
        return None

async def scrape_apniroots():
    url = "https://apniroots.com/collections/all"
    
    # Load previously scraped data if available to resume
    products_data = await load_previous_data(TEMP_SAVE_FILENAME)
    
    # Use a set to efficiently track product names already added to avoid duplicates
    existing_product_names = {p['name'] for p in products_data if p.get('name')}
    
    products_added_since_last_save = 0 # Counter for newly added products, triggers incremental save

    async with async_playwright() as p:
        # Launch browser in headless mode for performance
        browser = await p.chromium.launch(headless=True) 
        page = await browser.new_page()
        
        try:
            # Increased initial navigation timeout
            await page.goto(url, wait_until='domcontentloaded', timeout=60000) 

            # --- START KLAVIYO POPUP HANDLING ---
            print("Checking for Klaviyo popup and attempting to close...")
            try:
                popup_container_selector = 'div[data-testid="POPUP"]'
                # Wait for the main popup container to become visible
                await page.wait_for_selector(popup_container_selector, state='visible', timeout=7000)
                print("Klaviyo popup detected. Attempting to click close button...")
                
                # Click the specific close button within the popup
                close_button_selector = 'button[aria-label="Close dialog"]' 
                await page.click(close_button_selector, timeout=3000)
                print("Clicked Klaviyo popup close button.")
                
                # Give a moment for the popup animation to complete and disappear
                await asyncio.sleep(1) 
                await page.wait_for_selector(popup_container_selector, state='hidden', timeout=5000)
                print("Klaviyo popup successfully closed.")

            except TimeoutError:
                print("No Klaviyo popup detected or popup did not appear/close within the timeout.")
            except Exception as e:
                # Fallback: If clicking the button fails, try pressing Escape key
                print(f"Error during Klaviyo popup handling ({e}). Attempting to press Escape key as fallback.")
                await page.keyboard.press('Escape')
                await asyncio.sleep(1) 
                print("Pressed Escape key.")
            print("Popup handling complete. Proceeding with scraping.")
            # --- END KLAVIYO POPUP HANDLING ---

            print("Starting infinite scrolling to load all products...")
            
            last_height = await page.evaluate("document.body.scrollHeight")
            # Get the initial count of products already visible on the page
            current_product_count_on_page = len(await page.query_selector_all('product-item.product-collection'))
            no_change_scroll_attempts = 0 # Counter for consecutive scrolls without new content

            # Main scrolling loop
            while True:
                # Scroll to the very bottom of the page
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                # Wait for the network to be idle, or a sensible timeout if it never idles
                try:
                    await page.wait_for_load_state('networkidle', timeout=NETWORK_IDLE_TIMEOUT)
                    # print("Network idle state reached.") # Uncomment for more verbose logging
                except TimeoutError:
                    print("Network did not go idle within timeout, continuing scrolling check...")
                
                # Give a small additional pause for rendering newly loaded content
                await asyncio.sleep(SCROLL_PAUSE_TIME) 
                
                new_height = await page.evaluate("document.body.scrollHeight")
                
                # Get all currently visible product elements on the page
                all_product_elements_on_page = await page.query_selector_all('product-item.product-collection')
                new_product_count_on_page = len(all_product_elements_on_page)
                
                print(f"Scrolled. Page height: {new_height}, Current visible products: {new_product_count_on_page}")

                # Check if scroll height and product count on page have stopped increasing
                if new_height == last_height and new_product_count_on_page == current_product_count_on_page:
                    no_change_scroll_attempts += 1
                    print(f"No new content or product count increase. Attempt {no_change_scroll_attempts}/{MAX_NO_CHANGE_SCROLLS}")
                    if no_change_scroll_attempts >= MAX_NO_CHANGE_SCROLLS:
                        print("Reached maximum no-change scrolls. Ending scrolling.")
                        break # Exit loop if no new content is loaded consistently
                else:
                    no_change_scroll_attempts = 0 # Reset counter if new content is found
                
                last_height = new_height
                current_product_count_on_page = new_product_count_on_page

                # --- Data Extraction and Incremental Saving for newly found products ---
                # Iterate over all currently visible product elements and add only those
                # that haven't been processed yet (checked using existing_product_names set).
                
                for product_elem in all_product_elements_on_page:
                    # Product Name (required for duplicate check)
                    name_element = await product_elem.query_selector('h4 a')
                    product_name = await name_element.text_content() if name_element else None

                    # Only process if product_name exists and hasn't been scraped before
                    if product_name and product_name not in existing_product_names:
                        product = {}
                        product['name'] = product_name
                        
                        # Add to set immediately to mark as seen and prevent re-processing in future iterations
                        existing_product_names.add(product_name) 

                        # Price
                        price_element_sale = await product_elem.query_selector('span.price--sale[data-js-product-price]')
                        price_element_regular = await product_elem.query_selector('span.price[data-js-product-price]')
                        
                        raw_price = None
                        if price_element_sale:
                            raw_price = await price_element_sale.text_content()
                        elif price_element_regular:
                            raw_price = await price_element_regular.text_content()
                        
                        product['price'] = parse_price(raw_price)

                        # Description
                        desc_element = await product_elem.query_selector('p.product-collection__description')
                        # Use .strip() to remove leading/trailing whitespace
                        product['description'] = (await desc_element.text_content()).strip() if desc_element else None

                        # Rating (Not explicitly found in provided HTML; setting to None as float type)
                        # If a rating element exists, its text content would need to be parsed to float.
                        product['rating'] = None 

                        # Category (Inferred from the collection page URL: 'collections/all')
                        product['category'] = "All Products" 

                        # Availability
                        availability_element = await product_elem.query_selector('p[data-js-product-availability] span:nth-child(2)')
                        availability_text = None
                        if availability_element:
                            text_content = await availability_element.text_content()
                            if text_content:
                                # Standardize availability text for consistency
                                if "In Stock" in text_content:
                                    availability_text = "In Stock"
                                elif "Sold Out" in text_content:
                                    availability_text = "Sold Out"
                                else:
                                    availability_text = "Unknown" # Default if status not clearly stated
                        product['availability'] = availability_text

                        # Image URL
                        img_element = await product_elem.query_selector('img.rimage__img')
                        if img_element:
                            data_master_url = await img_element.get_attribute('data-master')
                            if data_master_url:
                                # Replace {width}x with a desired fixed width for consistent image quality
                                image_url = data_master_url.replace('{width}x', '1024x')
                                if not image_url.startswith('http'):
                                    image_url = 'https:' + image_url # Ensure absolute URL
                                product['image_url'] = image_url
                            else:
                                product['image_url'] = None
                        else:
                            product['image_url'] = None

                        products_data.append(product)
                        products_added_since_last_save += 1 # Increment counter for new products

                # Save partial data if enough new products have been collected since last save
                if products_added_since_last_save >= SAVE_INTERVAL_PRODUCTS:
                    await save_partial_data(products_data, TEMP_SAVE_FILENAME)
                    products_added_since_last_save = 0 # Reset counter

            print(f"Finished scrolling. Total unique products collected: {len(products_data)}")

        except Exception as e:
            print(f"An unexpected error occurred during scraping: {e}")
            print("Attempting to save current progress before exiting...")
            await save_partial_data(products_data, TEMP_SAVE_FILENAME) # Ensure data is saved on error
        finally:
            await browser.close()
    
    # Perform a final save if there's any unsaved data at the very end of scraping
    if products_added_since_last_save > 0: # Or if it's the first run and some data was collected
        await save_partial_data(products_data, TEMP_SAVE_FILENAME)
        
    return products_data

async def main():
    scraped_data = []
    try:
        scraped_data = await scrape_apniroots()
    except Exception as e:
        print(f"Main scraping process failed: {e}")
        # If scrape_apniroots itself fails before returning data,
        # ensure we still attempt to load partial data for final saving.
        print(f"Attempting to load any partial data from {TEMP_SAVE_FILENAME} if available for final save.")
        scraped_data = await load_previous_data(TEMP_SAVE_FILENAME)

    if scraped_data:
        # Save the final, complete data from the temporary file to the main output file
        with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(scraped_data, f, ensure_ascii=False, indent=4)
        print(f"Scraping complete. Final data saved to {OUTPUT_FILENAME}")
        
        # Clean up the temporary file after successful final save
        if os.path.exists(TEMP_SAVE_FILENAME):
            os.remove(TEMP_SAVE_FILENAME)
            print(f"Removed temporary file: {TEMP_SAVE_FILENAME}")
    else:
        print("No data was scraped or loaded to save.")
    
    print(f"Total products scraped: {len(scraped_data)}")

if __name__ == "__main__":
    asyncio.run(main())