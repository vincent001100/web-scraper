import requests
from bs4 import BeautifulSoup
import csv
from datetime import datetime
def scrape_products():
    url = "http://books.toscrape.com/catalogue/page-1.html"
    try:
        print("🔄 Connecting...")
        response = requests.get(url, timeout=10)
        print("✓ Connected")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        products = soup.find_all('article', class_='product_pod')
        print(f"✓ Found {len(products)} products")
        
        data = []
        for product in products:
            title = product.h2.a.get('title')
            price = product.find('p', class_='price_color').text
            rating = product.find('p', class_='star-rating').get('class')[1]
            data.append({'title': title, 'price': price, 'rating': rating})
        
        filename = f"products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['title', 'price', 'rating'])
            writer.writeheader()
            writer.writerows(data)
        
        print(f"✓ Saved to {filename}")
    except Exception as e:
        print(f"Error: {e}")
scrape_products()
