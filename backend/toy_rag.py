import os
from dotenv import load_dotenv
load_dotenv()
import pdfplumber
import chromadb
from chromadb.utils import embedding_functions
from langchain.text_splitter import RecursiveCharacterTextSplitter

def extract_text(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def chunk_text(text, source_name):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(text)
    return [{"text": c, "source": source_name} for c in chunks]

# Step 1: extract + chunk all PDFs
all_chunks = []
folder = "toy_pdfs"
for filename in os.listdir(folder):
    if filename.endswith(".pdf"):
        path = os.path.join(folder, filename)
        text = extract_text(path)
        chunks = chunk_text(text, filename)
        all_chunks.extend(chunks)

print(f"Total chunks: {len(all_chunks)}")

# Step 2: set up embedding function + Chroma
embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="./chroma_store")
collection = client.get_or_create_collection(name="toy_docs", embedding_function=embed_fn)

# Step 3: store chunks in Chroma
ids = [f"chunk_{i}" for i in range(len(all_chunks))]
documents = [c["text"] for c in all_chunks]
metadatas = [{"source": c["source"]} for c in all_chunks]

collection.add(ids=ids, documents=documents, metadatas=metadatas)
print(f"Stored {collection.count()} chunks in Chroma")

# Step 4: try a test query
query = "How tall is the Eiffel Tower?"
results = collection.query(query_texts=[query], n_results=3)

print(f"\nQuery: {query}")
for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
    print(f"\n[{meta['source']}]\n{doc}")

from groq import Groq

print("Loaded key:", os.getenv("GROQ_API_KEY"))
client_groq = Groq(api_key=os.getenv("GROQ_API_KEY"))

def ask_gemini(question, retrieved_chunks):
    context = "\n\n".join(
        f"[Source: {meta['source']}]\n{doc}"
        for doc, meta in zip(retrieved_chunks["documents"][0], retrieved_chunks["metadatas"][0])
    )
    prompt = f"""Answer the question using ONLY the context below. If the answer isn't in the context, say "I don't have enough information to answer that."

Context:
{context}

Question: {question}

Answer, and mention which source(s) you used:"""

    response = client_groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

question = "What is the population of Tokyo?"
retrieved = collection.query(query_texts=[question], n_results=3)
answer = ask_gemini(question, retrieved)

print(f"\n--- RAG Answer ---")
print(f"Question: {question}")
print(f"Answer: {answer}")