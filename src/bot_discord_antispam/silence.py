import discord
from discord.ext import commands
import time
import asyncio
from collections import defaultdict
import os
from dotenv import load_dotenv
import sys
import logging

class ThrottleGatewayFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.last_log_times = {}

    def filter(self, record):
        msg = record.getMessage()
        if "RESUMED session" in msg or "Can't keep up" in msg:
            now = time.time()
            key = "resumed" if "RESUMED session" in msg else "cant_keep_up"
            if now - self.last_log_times.get(key, 0) < 86400:
                return False
            self.last_log_times[key] = now
        return True

logging.getLogger('discord.gateway').addFilter(ThrottleGatewayFilter())

sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

# Chargement des variables d'environnement
LOG_CHANNEL_ID_STR = os.getenv("LOG_CHANNEL_ID")
MUTE_ROLE_NAME = os.getenv("MUTE_ROLE_NAME", "Silence")
STAFF_ROLE_NAME = os.getenv("STAFF_ROLE_NAME", "Staff")
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "Admin")

# Validation et conversion de LOG_CHANNEL_ID
if not LOG_CHANNEL_ID_STR:
    raise ValueError("La variable d'environnement LOG_CHANNEL_ID n'est pas définie. Vérifiez votre fichier .env")

try:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID_STR)
except ValueError as e:
    raise ValueError(f"Erreur lors de la conversion de LOG_CHANNEL_ID en entier: {e}")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_messages = defaultdict(list)     # Historique des messages
muted_users_roles = {}               # Sauvegarde des rôles avant mute
reported_users = set()               # Utilisateurs déjà traités

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user}", flush=True)

@bot.event
async def on_message(message):
    if message.author == bot.user or message.guild is None:
        return

    guild = message.guild
    member = guild.get_member(message.author.id)
    if not member:
        return

    # ✅ VÉRIFICATION STAFF/ADMIN - Ne pas traiter les membres staff ou admin
    has_staff = discord.utils.get(member.roles, name=STAFF_ROLE_NAME) is not None
    has_admin = discord.utils.get(member.roles, name=ADMIN_ROLE_NAME) is not None
    
    if has_staff or has_admin:
        await bot.process_commands(message)
        return

    has_apprenti = discord.utils.get(member.roles, name="Apprenti") is not None

    now = time.time()
    content = message.content.lower().strip()
    channel_id = message.channel.id

    # Extraction des empreintes de fichiers/images joints (nom, taille)
    attachment_signatures = tuple(sorted((att.filename, att.size) for att in message.attachments))
    has_attachments = len(attachment_signatures) > 0

    # Ajouter le message à l'historique
    user_messages[message.author.id].append((content, attachment_signatures, now, message, channel_id))

    # Créer une copie filtrée des messages dans les 5 dernières minutes
    recent_messages = [
        (msg, atts, timestamp, msg_obj, chan_id)
        for msg, atts, timestamp, msg_obj, chan_id in user_messages[message.author.id]
        if now - timestamp <= 300
    ]

    # Détecter les répétitions identiques (texte identique non vide OU images/pièces jointes identiques)
    identical_text_messages = []
    if content:
        identical_text_messages = [
            (msg, atts, timestamp, msg_obj, chan_id)
            for msg, atts, timestamp, msg_obj, chan_id in recent_messages
            if msg == content and now - timestamp <= 300
        ]

    identical_attachment_messages = []
    if has_attachments:
        identical_attachment_messages = [
            (msg, atts, timestamp, msg_obj, chan_id)
            for msg, atts, timestamp, msg_obj, chan_id in recent_messages
            if atts == attachment_signatures and now - timestamp <= 300
        ]

    # Sélectionner les messages incriminés prioritaires
    spam_type = None
    spam_messages = []
    if len(identical_attachment_messages) >= 3:
        spam_type = "image"
        spam_messages = identical_attachment_messages
    elif len(identical_text_messages) >= 3:
        spam_type = "texte"
        spam_messages = identical_text_messages

    should_mute = False
    if spam_messages:
        if not has_apprenti:
            # Utilisateur normal : 3 répétitions dans les 5 minutes suffisent
            should_mute = True
        else:
            # Apprenti : 3 répétitions ET dans au moins 2 canaux différents
            unique_channels = {chan_id for _, _, _, _, chan_id in spam_messages}
            if len(unique_channels) >= 2:
                should_mute = True

    if should_mute and member.id not in reported_users:
        reported_users.add(member.id)

        mute_role = discord.utils.get(guild.roles, name=MUTE_ROLE_NAME)
        if not mute_role:
            try:
                mute_role = await guild.create_role(name=MUTE_ROLE_NAME, reason="Rôle pour mute les spammeurs")
            except Exception:
                return

        # Sauvegarder les rôles actuels (hors @everyone ET hors Silence)
        roles_to_save = [role for role in member.roles if role != guild.default_role and role.name != MUTE_ROLE_NAME]
        muted_users_roles[member.id] = roles_to_save
        
        try:
            # Retirer tous les rôles sauf @everyone
            await member.remove_roles(*roles_to_save, reason="Mute pour spam")
            await member.add_roles(mute_role, reason="Spam détecté")
            print(f"Ban (mute): {member.name} a été mute pour spam ({spam_type}).", flush=True)
        except Exception:
            return

        # Log dans le canal
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            try:
                log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception as e:
                print(f"Erreur canal de log: {e}", flush=True)

        if log_channel:
            channels_info = ""
            if has_apprenti:
                unique_channels = {chan_id for _, _, _, _, chan_id in spam_messages}
                channels_info = f"\nCanaux concernés: {len(unique_channels)}"

            if spam_type == "image":
                filenames = ", ".join(att.filename for att in message.attachments)
                details = f"Images/fichiers répétés: `{filenames}`"
            else:
                details = f"Message répété: `{content}`"
            
            await log_channel.send(
                f" {member.mention} a été mute pour spam !{channels_info}\n\n"
                f"{details}\n"
                f"Nombre de répétitions: {len(spam_messages)} (dans les 5 dernières minutes)\n\n"
                f"Tapez `!Silence {member.mention}` pour lui redonner ses rôles."
            )

        # Supprimer les messages incriminés des 5 dernières minutes
        for _, _, _, msg_obj, _ in spam_messages:
            try:
                await msg_obj.delete()
            except Exception:
                pass

    # Nettoyage de l'historique (garde uniquement les 5 dernières minutes)
    user_messages[message.author.id] = recent_messages

    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def Silence(ctx, member: discord.Member):
    """Commande pour unmute un utilisateur et lui redonner ses rôles d'origine."""

    mute_role = discord.utils.get(ctx.guild.roles, name=MUTE_ROLE_NAME)
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except Exception as e:
            print(f"Erreur canal de log: {e}", flush=True)

    if member.id in muted_users_roles:
        try:
            # Retirer le rôle Silence
            if mute_role and mute_role in member.roles:
                await member.remove_roles(mute_role, reason="Unmute par un admin")

            # Redonner les rôles d'origine
            if muted_users_roles[member.id]:
                await member.add_roles(*muted_users_roles[member.id], reason="Retour des rôles")

            # ✅ CORRECTION : Nettoyer les données ET l'historique des messages
            del muted_users_roles[member.id]
            reported_users.discard(member.id)
            
            # Reset complet de l'historique des messages de l'utilisateur
            if member.id in user_messages:
                del user_messages[member.id]

            if log_channel:
                await log_channel.send(f" {member.mention} a été unmute et a récupéré ses rôles !")
            print(f"Unban (unmute): {member.name} a été unmute avec succès.", flush=True)

        except discord.Forbidden:
            await ctx.send("Permission insuffisante pour unmute.")
        except Exception as e:
            await ctx.send(f"Erreur pendant l'unmute : {e}")
    else:
        await ctx.send(f"❌ {member.mention} n'est pas dans la liste des utilisateurs muted.")

# Commande pour vérifier le statut d'un utilisateur (debug)
@bot.command()
@commands.has_permissions(manage_roles=True)
async def debug_user(ctx, member: discord.Member):
    """Commande de debug pour voir l'historique d'un utilisateur"""
    
    has_staff = discord.utils.get(member.roles, name=STAFF_ROLE_NAME) is not None
    has_apprenti = discord.utils.get(member.roles, name="Apprenti") is not None
    
    recent_count = len([msg for msg, atts, timestamp, _, _ in user_messages[member.id] if time.time() - timestamp <= 300])
    
    embed = discord.Embed(title=f"Debug: {member.display_name}", color=0x00ff00)
    embed.add_field(name="Rôles", value=f"Staff: {has_staff}\nApprenti: {has_apprenti}", inline=False)
    embed.add_field(name="Messages récents", value=f"{recent_count} messages dans les 5 dernières minutes", inline=False)
    embed.add_field(name="Muted", value=f"Oui" if member.id in muted_users_roles else "Non", inline=False)
    
    await ctx.send(embed=embed)


# Lancer le bot avec le token
bot.run(os.getenv("TOKEN"))
