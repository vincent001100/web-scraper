import requests
from bs4 import BeautifulSoup
import csv
import time
from datetime import datetime
from urllib.parse import urljoin
def scrape_products():
    url = "http://books.toscrape.com/catalogue/page-1.html"
    data = []
    page = 1
    try:
        # Keep going as long as there is a page to visit
        while url:
            print(f"🔄 Page {page}: connecting...")
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            products = soup.find_all('article', class_='product_pod')
            print(f"✓ Found {len(products)} products")
            
            for product in products:
                title = product.h3.a.get('title')
                price = product.find('p', class_='price_color').text
                rating = product.find('p', class_='star-rating').get('class')[1]
                data.append({'title': title, 'price': price, 'rating': rating})
            
            # Look for the "next" button; on the last page it doesn't exist, so we stop
            next_button = soup.find('li', class_='next')
            if next_button:
                url = urljoin(url, next_button.a.get('href'))
                page += 1
                time.sleep(1)  # wait 1 second between pages to be polite to the website
            else:
                url = None
        
        print(f"✓ Total: {len(data)} products from {page} pages")
        filename = f"products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['title', 'price', 'rating'])
            writer.writeheader()
            writer.writerows(data)
        
        print(f"✓ Saved to {filename}")
    except Exception as e:
        print(f"Error: {e}")
scrape_products()
