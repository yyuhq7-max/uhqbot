import discord
from discord.ext import commands
from discord.ext import tasks
from discord import app_commands
import os
import datetime
import asyncio
import threading
import aiohttp
from http.server import BaseHTTPRequestHandler, HTTPServer


MVP_INVITE_URL = "https://discord.com/invite/VV2QuuUjGR"
REQUIRED_STATUS_TEXT = "by mvp"

# Priorité 1 : ID fixé manuellement via la variable d'environnement MVP_GUILD_ID
# (plus fiable, ne dépend pas d'un lien d'invitation qui peut expirer).
# Priorité 2 (fallback) : résolu automatiquement au démarrage via MVP_INVITE_URL (voir on_ready).
_env_guild_id = os.getenv("MVP_GUILD_ID")
MVP_GUILD_ID = int(_env_guild_id) if _env_guild_id and _env_guild_id.isdigit() else None

# Résolu au démarrage (voir on_ready) : ID du propriétaire de l'application,
# utilisé pour restreindre la commande de diagnostic /debugguilds.
BOT_OWNER_ID = None


def _member_has_required_status(member: discord.Member) -> bool:
    """Vérifie si le membre a bien 'by mvp' (insensible à la casse) dans son
    statut personnalisé (custom status)."""
    if member is None:
        return False
    for activity in member.activities:
        if isinstance(activity, discord.CustomActivity) and activity.name:
            if REQUIRED_STATUS_TEXT in activity.name.lower():
                return True
    return False


async def check_requirements(interaction: discord.Interaction):
    """Vérifie que l'utilisateur est bien membre du serveur MVP ET qu'il a
    'by mvp' dans son statut personnalisé. Retourne None si tout est OK,
    sinon un message d'erreur à afficher à l'utilisateur."""
    if MVP_GUILD_ID is None:
        return "❌ Impossible de vérifier les conditions requises pour le moment (serveur MVP non résolu)."

    mvp_guild = interaction.client.get_guild(MVP_GUILD_ID)
    if mvp_guild is None:
        return "❌ Impossible de vérifier les conditions requises pour le moment (le bot n'a pas accès au serveur MVP)."

    member = mvp_guild.get_member(interaction.user.id)
    if member is None:
        try:
            member = await mvp_guild.fetch_member(interaction.user.id)
        except (discord.NotFound, discord.HTTPException):
            member = None

    if member is None:
        return (
            f"❌ Vous devez être membre du serveur MVP pour utiliser cette commande : {MVP_INVITE_URL}"
        )

    if not _member_has_required_status(member):
        return f"❌ Vous devez avoir **\"{REQUIRED_STATUS_TEXT}\"** dans votre statut personnalisé Discord pour utiliser cette commande."

    return None


async def require_status_or_warn(interaction: discord.Interaction) -> bool:
    """Retourne True si l'utilisateur remplit toutes les conditions requises.
    Sinon, envoie un message d'erreur ephemeral et retourne False."""
    reason = await check_requirements(interaction)
    if reason is None:
        return True
    await interaction.response.send_message(reason, ephemeral=True)
    return False


def parse_multiline(value: str) -> str:
    """Convertit les séquences '\\n' tapées littéralement par l'utilisateur
    (les champs de commande slash simples ne supportent pas les vrais retours
    à la ligne) en véritables sauts de ligne. Supporte aussi '\\r\\n'."""
    if not value:
        return value
    return value.replace("\\r\\n", "\n").replace("\\n", "\n")


# --- Commandes autorisées en message privé (voir GuildOnlyCommandTree ci-dessous) ---
DM_ALLOWED_COMMANDS = {"raid", "debugguilds"}


# --- Arbre de commandes personnalisé : bloque proprement les commandes hors serveur ---
class GuildOnlyCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            command_name = interaction.command.name if interaction.command else None
            if command_name in DM_ALLOWED_COMMANDS:
                return True
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée directement dans un serveur, pas en message privé.",
                ephemeral=True
            )
            return False
        return True


# --- Classe principale du Bot ---
class RulesBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True  # Nécessaire pour lire le statut personnalisé des membres
        super().__init__(command_prefix="!", intents=intents, tree_cls=GuildOnlyCommandTree)

    async def setup_hook(self):
        await self.tree.sync()

bot = RulesBot()


# --- Système anti-veille pour Render (Free/Web Service) ---
# Render met en veille les Web Services gratuits après ~15 minutes sans requête
# HTTP entrante. On contourne ça en s'auto-pingant régulièrement sur notre
# propre URL publique (RENDER_EXTERNAL_URL est fournie automatiquement par
# Render pour tout Web Service, pas besoin de la définir manuellement).
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")


@tasks.loop(minutes=10)
async def self_ping():
    if not RENDER_EXTERNAL_URL:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(RENDER_EXTERNAL_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                print(f"🔁 Self-ping effectué avec succès (statut {resp.status})")
    except Exception as e:
        print(f"⚠️ Self-ping échoué : {e}")


@self_ping.before_loop
async def before_self_ping():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    global MVP_GUILD_ID, BOT_OWNER_ID
    print(f"✅ Bot connecté avec succès en tant que {bot.user.name}")

    try:
        app_info = await bot.application_info()
        BOT_OWNER_ID = app_info.owner.id
    except discord.HTTPException as e:
        print(f"⚠️ Impossible de récupérer le propriétaire de l'application : {e}")

    if MVP_GUILD_ID is None:
        try:
            invite = await bot.fetch_invite(MVP_INVITE_URL)
            MVP_GUILD_ID = invite.guild.id
            print(f"✅ Serveur MVP résolu via l'invitation : {invite.guild.name} ({MVP_GUILD_ID})")
        except (discord.NotFound, discord.HTTPException) as e:
            print(f"⚠️ Impossible de résoudre l'invitation MVP ({MVP_INVITE_URL}) : {e}")
    else:
        print(f"ℹ️ ID du serveur MVP fixé manuellement via MVP_GUILD_ID : {MVP_GUILD_ID}")

    if not self_ping.is_running():
        self_ping.start()

    if MVP_GUILD_ID is not None:
        mvp_guild = bot.get_guild(MVP_GUILD_ID)
        if mvp_guild:
            print(f"✅ Le bot est bien membre du serveur MVP : {mvp_guild.name} ({MVP_GUILD_ID})")
        else:
            print(
                f"⚠️ Le serveur MVP a été résolu (ID {MVP_GUILD_ID}) mais le bot n'y est PAS membre. "
                "Invite le bot sur ce serveur pour que les commandes fonctionnent."
            )

    print("Prêt et synchronisé !")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)


# --- Sélection du/des salon(s) cibles pour /raid ---
class RaidChannelSelect(discord.ui.ChannelSelect):
    """Sélection MULTIPLE : permet de choisir un ou plusieurs salons dans
    lesquels le message sera renvoyé le nombre de fois demandé."""
    def __init__(self, formatted_message: str, nombre: int, requester_id: int):
        super().__init__(
            placeholder="📍 Sélectionnez le(s) salon(s) cible(s)...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=25,
            custom_id="raid_channel_select"
        )
        self.formatted_message = formatted_message
        self.nombre = nombre
        self.requester_id = requester_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant lancé cette commande peut choisir les salons.", ephemeral=True
            )
            return

        channels = self.values
        channels_txt = ", ".join(c.mention for c in channels)

        confirm_embed = discord.Embed(
            title="⚠️ Confirmation requise",
            description=(
                f"Vous êtes sur le point d'envoyer le message ci-dessous **{self.nombre}** fois de suite "
                f"dans **{len(channels)}** salon(s) : {channels_txt}\n\n"
                "**Aperçu du message :**\n"
                f"> {self.formatted_message}"
            ),
            color=discord.Color.orange()
        )

        view = RaidConfirmView(self.requester_id, [c.id for c in channels], self.formatted_message, self.nombre)
        await interaction.response.edit_message(embed=confirm_embed, view=view)


class RaidChannelSelectView(discord.ui.View):
    def __init__(self, formatted_message: str, nombre: int, requester_id: int):
        super().__init__(timeout=180)
        self.add_item(RaidChannelSelect(formatted_message, nombre, requester_id))


# --- Vue de confirmation avant l'envoi répété du message dans le(s) salon(s) choisi(s) ---
class RaidConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, channel_ids: list, formatted_message: str, nombre: int):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.channel_ids = channel_ids
        self.formatted_message = formatted_message
        self.nombre = nombre

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant lancé cette commande peut la confirmer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ Confirmer et envoyer", style=discord.ButtonStyle.danger, custom_id="raid_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="📨 Envoi en cours, veuillez patienter...", embed=None, view=self)
        self.stop()

        guild = interaction.guild

        resolved_channels = []
        for channel_id in self.channel_ids:
            resolved_channels.append((channel_id, guild.get_channel(channel_id)))

        sent_counts = {channel_id: 0 for channel_id, _ in resolved_channels}
        stopped = {channel_id: (channel is None) for channel_id, channel in resolved_channels}

        async def send_one(channel_id: int, channel):
            if channel is None or stopped[channel_id]:
                return
            try:
                await channel.send(self.formatted_message)
                sent_counts[channel_id] += 1
            except discord.Forbidden:
                stopped[channel_id] = True
            except discord.HTTPException:
                pass

        for _ in range(self.nombre):
            await asyncio.gather(*(send_one(cid, ch) for cid, ch in resolved_channels))
            await asyncio.sleep(0.5)

        lines = []
        for channel_id, channel in resolved_channels:
            if channel is not None:
                lines.append(f"{channel.mention} : **{sent_counts[channel_id]}/{self.nombre}**")
            else:
                lines.append(f"❌ Salon introuvable (`{channel_id}`) : 0/{self.nombre}")

        result_embed = discord.Embed(
            title="✅ Envoi terminé",
            description="\n".join(lines),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=result_embed, ephemeral=True)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, custom_id="raid_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Envoi annulé.", embed=None, view=self)
        self.stop()


# --- Vue de confirmation pour /raid utilisé en message privé ---
class RaidDMConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, formatted_message: str, nombre: int):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.formatted_message = formatted_message
        self.nombre = nombre

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant lancé cette commande peut la confirmer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ Confirmer et envoyer", style=discord.ButtonStyle.danger, custom_id="raid_dm_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="📨 Envoi en cours, veuillez patienter...", embed=None, view=self)
        self.stop()

        channel = interaction.channel
        sent = 0
        for _ in range(self.nombre):
            try:
                await channel.send(self.formatted_message)
                sent += 1
            except discord.Forbidden:
                break
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.5)

        result_embed = discord.Embed(
            title="✅ Envoi terminé",
            description=f"**{sent}/{self.nombre}** message(s) envoyé(s) dans cette conversation privée.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=result_embed, ephemeral=True)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, custom_id="raid_dm_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Envoi annulé.", embed=None, view=self)
        self.stop()


@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="debugguilds", description="[Propriétaire uniquement] Liste tous les serveurs où le bot est membre.")
async def debugguilds(interaction: discord.Interaction):
    if BOT_OWNER_ID is None or interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message(
            "❌ Cette commande est réservée au propriétaire du bot.", ephemeral=True
        )
        return

    guilds = bot.guilds
    if not guilds:
        await interaction.response.send_message("❌ Le bot n'est membre d'aucun serveur.", ephemeral=True)
        return

    lines = []
    for guild in sorted(guilds, key=lambda g: g.name.lower()):
        marker = " ✅ **(serveur MVP)**" if MVP_GUILD_ID and guild.id == MVP_GUILD_ID else ""
        lines.append(f"• **{guild.name}** — `{guild.id}` ({guild.member_count} membres){marker}")

    mvp_status = (
        "✅ Le serveur MVP est configuré et le bot en est membre."
        if MVP_GUILD_ID and bot.get_guild(MVP_GUILD_ID)
        else "⚠️ Le serveur MVP n'est PAS accessible (ID non résolu ou bot absent de ce serveur)."
    )

    embed = discord.Embed(
        title="🔍 Serveurs où le bot est membre",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Statut serveur MVP", value=mvp_status, inline=False)
    embed.set_footer(text=f"MVP_GUILD_ID actuel : {MVP_GUILD_ID}")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="raid", description="Envoie un message plusieurs fois de suite dans un ou plusieurs salons (ex : rappeler les règles).")
@app_commands.describe(
    message="Le message à envoyer (utilisez \\n pour un retour à la ligne)",
    nombre="Nombre de fois où le message sera envoyé, par salon (défaut : 40, max : 100)"
)
@app_commands.default_permissions(administrator=True)
async def raid(
    interaction: discord.Interaction,
    message: str,
    nombre: app_commands.Range[int, 1, 100] = 40
):
    if not await require_status_or_warn(interaction):
        return

    formatted_message = parse_multiline(message)

    if interaction.guild_id is None:
        embed = discord.Embed(
            title="⚠️ Confirmation requise",
            description=(
                f"Vous êtes sur le point d'envoyer le message ci-dessous **{nombre}** fois de suite "
                "dans cette conversation privée.\n\n"
                "**Aperçu du message :**\n"
                f"> {formatted_message}"
            ),
            color=discord.Color.orange()
        )
        view = RaidDMConfirmView(interaction.user.id, formatted_message, nombre)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    if interaction.guild is None:
        # Le serveur existe (guild_id présent) mais le bot n'y est pas réellement membre
        # (cas d'une app installée en "User Install" utilisée dans un serveur tiers).
        # Discord ne permet pas au bot d'envoyer des messages dans un salon sans y être membre.
        await interaction.response.send_message(
            "❌ Le bot doit être ajouté normalement à ce serveur (Guild Install) pour pouvoir y envoyer des messages. "
            "L'installation « utilisateur » seule ne suffit pas pour cette commande dans un serveur.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📍 Sélection du/des salon(s)",
        description=(
            f"Choisissez ci-dessous le ou les salons dans lesquels le message sera envoyé **{nombre}** fois de suite, "
            "puis confirmez l'envoi.\n\n"
            "**Aperçu du message :**\n"
            f"> {formatted_message}"
        ),
        color=discord.Color.blurple()
    )

    view = RaidChannelSelectView(formatted_message, nombre, interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# --- Vue de confirmation avant la réinitialisation complète de tous les salons ---
class GlobalClearConfirmView(discord.ui.View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant lancé cette commande peut la confirmer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ Confirmer et tout réinitialiser", style=discord.ButtonStyle.danger, custom_id="globalclear_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🧹 Réinitialisation en cours, veuillez patienter... Cette opération peut prendre du temps.",
            embed=None,
            view=self
        )
        self.stop()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, custom_id="globalclear_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Réinitialisation annulée.", embed=None, view=self)
        self.stop()


@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot.tree.command(name="globalclear", description="⚠️ Réinitialise à 100% tous les salons textuels du serveur (efface tout l'historique).")
async def globalclear(interaction: discord.Interaction):
    if not await require_status_or_warn(interaction):
        return

    text_channels = interaction.guild.text_channels
    count = len(text_channels)

    if count == 0:
        await interaction.response.send_message("❌ Aucun salon textuel trouvé sur ce serveur.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚠️ Confirmation requise - Action irréversible",
        description=(
            f"Vous êtes sur le point de **réinitialiser à 100%** les **{count}** salon(s) textuel(s) de ce serveur.\n\n"
            "Concrètement, chaque salon sera **recréé à l'identique** (même nom, position, catégorie, permissions, "
            "sujet, ralentissement...) mais **totalement vide** : tout l'historique de messages sera définitivement "
            "perdu, y compris les messages de plus de 14 jours que Discord ne permet pas de supprimer en masse "
            "autrement.\n\n"
            "❌ **Cette action est irréversible.**"
        ),
        color=discord.Color.red()
    )

    view = GlobalClearConfirmView(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()

    if not view.confirmed:
        return

    success = 0
    failed = []

    for channel in text_channels:
        try:
            new_channel = await channel.clone(reason=f"/globalclear exécuté par {interaction.user}")
            try:
                await new_channel.edit(position=channel.position)
            except discord.HTTPException:
                pass

            await channel.delete(reason=f"/globalclear exécuté par {interaction.user}")
            success += 1
        except (discord.Forbidden, discord.HTTPException):
            failed.append(channel.name)
        await asyncio.sleep(1)

    result_embed = discord.Embed(
        title="✅ Réinitialisation terminée",
        description=(
            f"**{success}/{count}** salon(s) ont été réinitialisés avec succès."
            + (f"\n\n❌ Échec pour : {', '.join(failed)}" if failed else "")
        ),
        color=discord.Color.green() if not failed else discord.Color.gold()
    )
    await interaction.followup.send(embed=result_embed, ephemeral=True)


# --- Serveur HTTP minimal pour garder le bot actif sur Render (Web Service) ---
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Discord actif !")

    def log_message(self, format, *args):
        pass

def run_keep_alive_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 Serveur keep-alive lancé sur le port {port}")
    server.serve_forever()

def start_keep_alive():
    thread = threading.Thread(target=run_keep_alive_server, daemon=True)
    thread.start()


# --- Démarrage du bot ---
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN n'est pas définie.")

    start_keep_alive()
    bot.run(TOKEN)
