# ?? GUIDE DE DÉPLOIEMENT SUR RENDER.COM (100% GRATUIT)

Suivez ces 3 étapes simples pour mettre votre serveur EduShop en ligne 24h/24 :

---

### Étape 1 : Mettre le dossier sur GitHub (ou GitLab)
1. Allez sur [github.com](https://github.com) et connectez-vous (créez un compte gratuit si vous n'en avez pas).
2. Créez un nouveau dépôt privé ou public nommé **edushop-server**.
3. Glissez-déposez tous les fichiers du dossier **EduShop_Cloud_Server** dans votre dépôt GitHub et validez (*Commit*).

---

### Étape 2 : Connecter sur Render.com
1. Allez sur [render.com](https://render.com) et créez un compte gratuit (en cliquant sur "Sign in with GitHub").
2. Cliquez sur le bouton bleu **New +** en haut à droite -> Sélectionnez **Web Service**.
3. Choisissez votre dépôt **edushop-server**.
4. Remplissez les champs (la plupart sont automatiques) :
   - **Name** : edushop-magasin (ou le nom de votre choix)
   - **Language** : Python 3
   - **Build Command** : pip install -r requirements.txt
   - **Start Command** : python -m uvicorn server:app --host 0.0.0.0 --port 
   - **Instance Type** : Free
5. Cliquez sur **Create Web Service**.

---

### Étape 3 : Récupérer votre URL et l'utiliser !
1. Render va afficher votre URL publique sécurisée en haut de page (ex: https://edushop-magasin.onrender.com).
2. **Pour vous (Admin)** : Ouvrez https://edushop-magasin.onrender.com/admin depuis votre smartphone ou PC.
3. **Pour la Caisse Vendeur** : Lancez EduShop_Seller.exe, cliquez sur **?? Paramètres**, collez https://edushop-magasin.onrender.com et cliquez sur **Enregistrer**.

Tout est prêt et synchronisé en continu dans le Cloud !
