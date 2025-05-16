import asyncio
from playwright.async_api import async_playwright, TimeoutError
import json
import re

async def scrape_apniroots():
    url = "https://apniroots.com/collections/all"
    products_data = []

    async with async_playwright() as p:
        # Launch browser in non-headless mode initially for easier debugging
        # Once popup handling is confirmed, you can change headless=True
        browser = await p.chromium.launch(headless=True) 
        page = await browser.new_page()
        await page.goto(url, wait_until='domcontentloaded')

        # --- START KLAVIYO POPUP HANDLING ---
        print("Checking for Klaviyo popup and attempting to close...")
        try:
            # 1. Wait for the main popup container to appear.
            # Based on the provided HTML, 'div[data-testid="POPUP"]' is a robust selector for the main popup wrapper.
            popup_container_selector = 'div[data-testid="POPUP"]'
            await page.wait_for_selector(popup_container_selector, state='visible', timeout=7000) # Increased timeout slightly
            print("Klaviyo popup detected. Attempting to click close button...")
            
            # 2. Click the specific close button within the popup.
            # From the HTML: <button ... aria-label="Close dialog" class="needsclick klaviyo-close-form ...">
            close_button_selector = 'button[aria-label="Close dialog"]' 
            await page.click(close_button_selector, timeout=3000) # Added timeout for clicking as well
            print("Clicked Klaviyo popup close button.")
            
            # 3. Give a moment for the popup animation to complete and disappear.
            await asyncio.sleep(1) 

            # Optional: Wait for the popup to be hidden (more robust check for success)
            await page.wait_for_selector(popup_container_selector, state='hidden', timeout=5000)
            print("Klaviyo popup successfully closed.")

        except TimeoutError:
            print("No Klaviyo popup detected or popup did not appear/close within the timeout.")
        except Exception as e:
            # Fallback: If clicking the button fails for any other reason, try pressing Escape.
            print(f"Error clicking Klaviyo popup close button ({e}). Attempting to press Escape key as fallback.")
            await page.keyboard.press('Escape')
            await asyncio.sleep(1) # Give time for popup to disappear
            print("Pressed Escape key.")

        print("Popup handling complete. Proceeding with scraping.")
        # --- END KLAVIYO POPUP HANDLING ---

        print("Starting pure infinite scrolling to load all products (waiting longer for data)...")
        
        last_height = await page.evaluate("document.body.scrollHeight")
        
        while True:
            # Scroll to the very bottom of the page
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Wait for content to load. Increased sleep duration as requested.
            # You might need to experiment with 5, 6, or even 8 seconds if it still quits early.
            await asyncio.sleep(5) 
            
            new_height = await page.evaluate("document.body.scrollHeight")
            print(f"Scrolled. Current page height: {new_height}")

            # Check if the scroll height has stopped increasing
            if new_height == last_height:
                print("No new content loaded, reached the end of scrolling.")
                break # Exit loop if no new content is loaded
            
            last_height = new_height

        print("Finished scrolling. Extracting product data...")

        print("Finished scrolling. Extracting product data...")
        # --- END INCREMENTAL SCROLLING ---

        # --- START DATA EXTRACTION ---
        product_elements = await page.query_selector_all('product-item.product-collection')

        for product_elem in product_elements:
            product = {}

            # Product Name
            name_element = await product_elem.query_selector('h4 a')
            product['Product Name'] = await name_element.text_content() if name_element else None

            # Price
            price_element_sale = await product_elem.query_selector('span.price--sale[data-js-product-price]')
            price_element_regular = await product_elem.query_selector('span.price[data-js-product-price]')
            
            if price_element_sale:
                product['Price'] = await price_element_sale.text_content()
            elif price_element_regular:
                product['Price'] = await price_element_regular.text_content()
            else:
                product['Price'] = None

            # Description
            desc_element = await product_elem.query_selector('p.product-collection__description')
            product['Description'] = await desc_element.text_content() if desc_element else None

            # Rating (Not explicitly found in provided HTML)
            product['Rating'] = None

            # Category (Inferred from the collection page URL)
            product['Category'] = "Sale"

            # Availability
            availability_element = await product_elem.query_selector('p[data-js-product-availability] span:nth-child(2)')
            product['Availability'] = await availability_element.text_content() if availability_element else None

            # Image URL
            img_element = await product_elem.query_selector('img.rimage__img')
            if img_element:
                data_master_url = await img_element.get_attribute('data-master')
                if data_master_url:
                    image_url = data_master_url.replace('{width}x', '1024x')
                    if not image_url.startswith('http'):
                        image_url = 'https:' + image_url
                    product['Image URL'] = image_url
                else:
                    product['Image URL'] = None
            else:
                product['Image URL'] = None

            products_data.append(product)
        # --- END DATA EXTRACTION ---

        await browser.close()
    
    return products_data

async def main():
    scraped_data = await scrape_apniroots()
    
    output_filename = "apniroots_sale_products.json"
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, ensure_ascii=False, indent=4)
    
    print(f"Scraping complete. Data saved to {output_filename}")
    print(f"Total products scraped: {len(scraped_data)}")

if __name__ == "__main__":
    asyncio.run(main())