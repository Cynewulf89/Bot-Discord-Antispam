# Utiliser une image Python  
FROM python:3.11-slim

# Définir le répertoire de travail   
WORKDIR /app 

# Copier les requirements d'abord pour tirer parti du cache Docker
COPY requirements.txt ./

# Installer les dépendances 
RUN apt-get update && \ 
    apt-get install -y --no-install-recommends && \ 
    pip install --no-cache-dir -r requirements.txt && \ 
    apt-get remove -y gcc libc-dev && \ 
    rm requirements.txt && \ 
    apt-get clean && \ 
    apt-get autoremove -y && \ 
    rm -rf /var/lib/apt/lists/* 

# Copier le reste des fichiers (y compris .env)
COPY . /app 

# Lancer l’application  
CMD ["python", "app/silence.py"]
