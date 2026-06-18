import requests

APP_ID = "6744523968"

url = f"https://itunes.apple.com/us/rss/customerreviews/page=1/id={APP_ID}/sortby=mostrecent/xml"

response = requests.get(url)

print(response.text[:2000])