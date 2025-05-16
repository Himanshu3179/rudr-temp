import requests
from bs4 import BeautifulSoup
import time # For polite crawling
import re   # For cleaning text (e.g., price, rating)
import json # To save data as JSON

# --- Configuration ---
SHOP_BASE_URL = "https://apniroots.com/collections/sale"
OUTPUT_FILENAME = "products_data.json"

# --- Web Scraping Functions ---
def get_page_content(url):
    """Fetches HTML content from a given URL."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_product_details(product_url):
    """
    Extracts detailed information from a single product detail page.
    (Selectors for individual product page remain as previously defined based on your earlier snippet)
    """
    html_content = get_page_content(product_url)
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    product_data = {
        "original_url": product_url
    }

    try:
        # Product Name: <h4 class="m-0"> inside <div class="product-collection__title mb-3">
        name_div = soup.find('div', class_='product-collection__title')
        name_tag = name_div.find('h4').find('a') if name_div else None
        product_data['product_name'] = name_tag.text.strip() if name_tag else 'N/A'

        # Price: <span class="price price--sale">. Get the last <span> child for current/sale price.
        price_span_container = soup.find('div', class_='product-collection__price')
        if price_span_container:
            price_spans = price_span_container.find('span', class_='price--sale')
            if price_spans:
                current_price_tag = price_spans.find_all('span')[-1]
                price_text = current_price_tag.text.strip()
                cleaned_price = re.sub(r'[^\d.]', '', price_text)
                product_data['price'] = float(cleaned_price) if cleaned_price else 0.0
            else: # Fallback for non-sale items
                single_price_tag = price_span_container.find('span', class_='price')
                if single_price_tag:
                    amount_tag = single_price_tag.find('bdi')
                    price_text = amount_tag.text.strip() if amount_tag else single_price_tag.text.strip()
                    cleaned_price = re.sub(r'[^\d.]', '', price_text)
                    product_data['price'] = float(cleaned_price) if cleaned_price else 0.0
                else:
                    product_data['price'] = 0.0
        else:
            product_data['price'] = 0.0

        # Description: <p class="m-0"> inside <div class="product-collection__description d-none mb-15">
        desc_div = soup.find('div', class_='product-collection__description')
        desc_tag = desc_div.find('p', class_='m-0') if desc_div else None
        product_data['description'] = desc_tag.get_text(separator=' ', strip=True) if desc_tag else 'N/A'

        # Rating: The provided HTML snippet does not show a visible star rating element.
        product_data['rating'] = 0.0

        # Category: Using Vendor as Category for simplicity based on provided snippet.
        vendor_info_div = soup.find('div', class_='product-collection__more-info')
        vendor_tag = vendor_info_div.find('a') if vendor_info_div else None
        product_data['category'] = vendor_tag.text.strip() if vendor_tag else 'N/A'

        # Availability: <p data-js-product-availability=""> inside <div class="product-collection__availability">
        availability_div = soup.find('div', class_='product-collection__availability')
        if availability_div:
            availability_span = availability_div.find('span')
            if availability_span:
                product_data['availability'] = "in stock" in availability_span.text.lower()
            else:
                product_data['availability'] = True
        else:
            product_data['availability'] = True

        # Image URL: <img data-master="..."> inside <div class="rimage">
        rimage_div = soup.find('div', class_='rimage')
        img_tag = rimage_div.find('img') if rimage_div else None
        
        if img_tag and 'data-master' in img_tag.attrs:
            base_image_url = img_tag['data-master'].replace('{width}x', '1000x')
            product_data['image_url'] = "https:" + base_image_url if base_image_url.startswith('//') else base_image_url
        else:
            product_data['image_url'] = 'N/A'

        print(f"Successfully extracted details for: {product_data['product_name']} (Price: {product_data['price']})")
        return product_data

    except Exception as e:
        print(f"Error parsing product page {product_url}: {e}")
        return None

def crawl_shop_pages(base_shop_url):
    """Crawls all pages of the shop, extracts product details, and returns them."""
    all_products_data = []
    page_num = 1
    while True:
        current_page_url = f"{base_shop_url}/page/{page_num}/" if page_num > 1 else base_shop_url
        print(f"\n--- Crawling shop page: {current_page_url} ---")
        html_content = get_page_content(current_page_url)
        if not html_content:
            print(f"Failed to fetch shop page {current_page_url}. Stopping pagination.")
            break

        soup = BeautifulSoup(html_content, 'html.parser')
        
        # --- CRITICAL CHANGE HERE: Targeting the product container on the listing page ---
        # Based on your latest screenshot, each product is directly inside this div:
        product_list_items = soup.find_all('div', class_='col-sm-6 col-md-4 col-lg-4 col-xl-4')

        if not product_list_items:
            print("No more products found on this page using the selector 'col-sm-6 col-md-4 col-lg-4 col-xl-4'.")
            print("This usually means no more products or the selector for product list items is incorrect.")
            print("Please double-check the HTML of 'https://apniroots.com/shop' for product containers.")
            break

        for item in product_list_items:
            # Find the link to the individual product page within the item
            # It's an 'a' tag whose href contains '/products/'
            product_link_tag = item.find('a', href=re.compile(r'/products/'))
            if product_link_tag and 'href' in product_link_tag.attrs:
                product_url = product_link_tag['href']
                # Ensure the URL is absolute
                if not product_url.startswith('http'):
                    product_url = requests.compat.urljoin(base_shop_url, product_url)
                
                # Ensure it's a product detail link (e.g., not a category link like /products/collection-name)
                # A simple check: a product link usually doesn't end with a slash if it's a specific product,
                # or contains a hyphenated product name.
                if '/products/' in product_url and not product_url.endswith('/'): 
                    product_details = parse_product_details(product_url)
                    if product_details:
                        all_products_data.append(product_details)
                time.sleep(0.5) # Be polite: wait between product page requests

        # Pagination logic: Find the "Next" button or page links
        # Assuming typical Shopify/WooCommerce pagination structure
        # Look for a navigation element with a 'next' link
        pagination_nav = soup.find('nav', class_='woocommerce-pagination') # WooCommerce fallback
        if not pagination_nav:
            pagination_nav = soup.find('div', class_='pagination-bar__wrapper') # Common Shopify pagination wrapper
            
        next_page_link_element = None
        if pagination_nav:
            next_link_tag = pagination_nav.find('a', class_='next') # Common for Shopify/WooCommerce next page button
            if not next_link_tag:
                 next_link_tag = pagination_nav.find('a', class_='next page-numbers') # Another common class

            if next_link_tag and 'href' in next_link_tag.attrs:
                next_page_link_element = next_link_tag['href']

        if next_page_link_element:
            # Ensure it's an absolute URL
            if not next_page_link_element.startswith('http'):
                next_page_url = requests.compat.urljoin(base_shop_url, next_page_link_element)
            else:
                next_page_url = next_page_link_element
            
            # Simple check to prevent infinite loop on last page if 'next' link always points to same page
            if next_page_url == current_page_url:
                print("Next page link is the same as current page. Stopping pagination.")
                break

            page_num += 1 # Increment page number for the next iteration
            time.sleep(1) # Be polite: wait longer between main page requests
        else:
            print("No 'next' page link found. Stopping pagination.")
            break
    
    return all_products_data

# --- Main Execution ---
if __name__ == "__main__":
    print("Starting product crawl...")
    scraped_data = crawl_shop_pages(SHOP_BASE_URL)
    
    # Save the collected data to a JSON file
    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, indent=4, ensure_ascii=False)
    
    print(f"\nCrawling finished! Total products scraped: {len(scraped_data)}")
    print(f"Data saved to {OUTPUT_FILENAME}")