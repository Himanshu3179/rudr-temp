from elasticsearch import Elasticsearch
import json

# Connect to local Elasticsearch
es = Elasticsearch("http://localhost:9200")

# Create index with mapping
index_name = "products"
mapping = {
    "mappings": {
        "properties": {
            "name": {"type": "text"},
            "price": {"type": "float"},
            "description": {"type": "text"},
            "rating": {"type": "float"},
            "category": {"type": "keyword"},
            "availability": {"type": "keyword"},
            "image_url": {"type": "keyword"}
        }
    }
}

# Delete old index if exists
if es.indices.exists(index=index_name):
    es.indices.delete(index=index_name)

# Create new index
es.indices.create(index=index_name, body=mapping)

# Index data
with open("products.json") as f:
    products = json.load(f)

for i, product in enumerate(products):
    es.index(index=index_name, id=i, body=product)

print("✅ Indexed all products!")
