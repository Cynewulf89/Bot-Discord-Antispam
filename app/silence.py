import discord
from discord.ext import commands
import time
import asyncio
from collections import defaultdict
import os
from dotenv import load_dotenv
import sys

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
        role_type = "admin" if has_admin else "staff"
        print(f" {member} est {role_type}, ignoré par l'anti-spam", flush=True)
        await bot.process_commands(message)
        return

    has_apprenti = discord.utils.get(member.roles, name="Apprenti") is not None

    now = time.time()
    content = message.content.lower().strip()
    channel_id = message.channel.id

    # Ajouter le message à l'historique
    user_messages[message.author.id].append((content, now, message, channel_id))

    # Créer une copie filtrée des messages dans les 5 dernières minutes
    recent_messages = [
        (msg, timestamp, msg_obj, chan_id)
        for msg, timestamp, msg_obj, chan_id in user_messages[message.author.id]
        if now - timestamp <= 300
    ]

    # ✅ CORRECTION : Détecter le spam (3 messages IDENTIQUES dans les 5 dernières minutes)
    identical_messages = [(msg, timestamp, msg_obj, chan_id) for msg, timestamp, msg_obj, chan_id in recent_messages if msg == content and msg.strip() != "" and now - timestamp <= 300]
    should_mute = False

    print(f"{member.name} - Messages identiques dans les 5 min: {len(identical_messages)} (contenu: '{content}')", flush=True)

    if not has_apprenti:
        # Utilisateur normal : 3 messages identiques dans les 5 minutes suffisent
        if len(identical_messages) >= 3:
            should_mute = True
            print(f"{member.name} (normal) - Spam détecté: {len(identical_messages)} messages identiques en 5 min", flush=True)
    else:
        # Apprenti : 3 messages identiques ET dans au moins 2 canaux différents (dans les 5 min)
        unique_channels = {chan_id for msg, _, _, chan_id in identical_messages}
        if len(identical_messages) >= 3 and len(unique_channels) >= 2:
            should_mute = True
            print(f"{member.name} (apprenti) - Spam détecté: {len(identical_messages)} messages identiques dans {len(unique_channels)} canaux en 5 min", flush=True)

    if should_mute and member.id not in reported_users:
        reported_users.add(member.id)

        mute_role = discord.utils.get(guild.roles, name=MUTE_ROLE_NAME)
        if not mute_role:
            try:
                mute_role = await guild.create_role(name=MUTE_ROLE_NAME, reason="Rôle pour mute les spammeurs")
                print(f" Rôle '{MUTE_ROLE_NAME}' créé", flush=True)
            except Exception as e:
                print(f"Impossible de créer le rôle '{MUTE_ROLE_NAME}' : {e}", flush=True)
                return

        # ✅ CORRECTION : Sauvegarder les rôles actuels (hors @everyone ET hors Silence)
        roles_to_save = [role for role in member.roles if role != guild.default_role and role.name != MUTE_ROLE_NAME]
        muted_users_roles[member.id] = roles_to_save
        
        try:
            # Retirer tous les rôles sauf @everyone
            await member.remove_roles(*roles_to_save, reason="Mute pour spam")
            await member.add_roles(mute_role, reason="Spam détecté")
            print(f" {member} a été mute. Rôles sauvegardés: {[r.name for r in roles_to_save]}", flush=True)
        except Exception as e:
            print(f" Erreur lors du mute de {member}: {e}", flush=True)
            return

        # Log dans le canal
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            channels_info = ""
            if has_apprenti:
                unique_channels = {chan_id for msg, _, _, chan_id in identical_messages}
                channels_info = f"\nCanaux concernés: {len(unique_channels)}"
            
            await log_channel.send(
                f" {member.mention} a été mute pour spam !{channels_info}\n\n"
                f"Message répété: `{content}`\n"
                f"Nombre de répétitions: {len(identical_messages)} (dans les 5 dernières minutes)\n\n"
                f"Tapez `!Silence {member.mention}` pour lui redonner ses rôles."
            )

        # 🧹 Supprimer SEULEMENT les messages identiques des 5 dernières minutes
        deleted_count = 0
        for msg, timestamp, msg_obj, _ in identical_messages:
            try:
                await msg_obj.delete()
                deleted_count += 1
                print(f"Message supprimé : {msg_obj.content[:50]}...", flush=True)
            except Exception as e:
                print(f" Erreur suppression message : {e}", flush=True)
        
        print(f" {deleted_count} messages supprimés pour {member.name}", flush=True)

    # Nettoyage de l'historique (garde uniquement les 5 dernières minutes)
    user_messages[message.author.id] = recent_messages

    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def Silence(ctx, member: discord.Member):
    """Commande pour unmute un utilisateur et lui redonner ses rôles d'origine."""

    mute_role = discord.utils.get(ctx.guild.roles, name=MUTE_ROLE_NAME)
    log_channel = bot.get_channel(LOG_CHANNEL_ID)

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
                print(f" Historique des messages effacé pour {member.name}", flush=True)

            if log_channel:
                await log_channel.send(f" {member.mention} a été unmute et a récupéré ses rôles !")

            print(f" {member} unmute avec succès.", flush=True)

        except discord.Forbidden:
            await ctx.send("Permission insuffisante pour unmute.")
            print("Permission insuffisante pour unmute.", flush=True)
        except Exception as e:
            await ctx.send(f"Erreur pendant l'unmute : {e}")
            print(f"Erreur pendant l'unmute : {e}", flush=True)
    else:
        await ctx.send(f"❌ {member.mention} n'est pas dans la liste des utilisateurs muted.")

# Commande pour vérifier le statut d'un utilisateur (debug)
@bot.command()
@commands.has_permissions(manage_roles=True)
async def debug_user(ctx, member: discord.Member):
    """Commande de debug pour voir l'historique d'un utilisateur"""
    
    has_staff = discord.utils.get(member.roles, name=STAFF_ROLE_NAME) is not None
    has_apprenti = discord.utils.get(member.roles, name="Apprenti") is not None
    
    recent_count = len([msg for msg, timestamp, _, _ in user_messages[member.id] if time.time() - timestamp <= 300])
    
    embed = discord.Embed(title=f"Debug: {member.display_name}", color=0x00ff00)
    embed.add_field(name="Rôles", value=f"Staff: {has_staff}\nApprenti: {has_apprenti}", inline=False)
    embed.add_field(name="Messages récents", value=f"{recent_count} messages dans les 5 dernières minutes", inline=False)
    embed.add_field(name="Muted", value=f"Oui" if member.id in muted_users_roles else "Non", inline=False)
    
    await ctx.send(embed=embed)


# Lancer le bot avec le token
bot.run(os.getenv("TOKEN"))
