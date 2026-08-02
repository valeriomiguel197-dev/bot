import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands

# --- 1. CONFIGURACIÓN DE ROLES Y CANALES ---
CANAL_RECOMENDACIONES_ID = 1517311566591168562  # ID de tu canal de recomendaciones

# ⚠️ PONÉ ACÁ LA ID DEL ROL DE MODERADOR
ROL_MODERADOR_ID = 1516746824961097778

NIVELES_CONFIANZA = {
    1: 1518773836156244058,  # ID Rol Nivel 1
    2: 1518773940766380264,  # ID Rol Nivel 2
    3: 1518774004784173066,  # ID Rol Nivel 3
    4: 1518774055229194486,  # ID Rol Nivel 4
    5: 1518774106995032125,  # ID Rol Nivel 5
    6: 1516144475494158480   # ID Rol Confiable (Nivel 6 / Máximo)
}

# --- 2. BASE DE DATOS LOCAL Y PERSISTENTE ---
DB_DIR = "/app/data"
DB_PATH = os.path.join(DB_DIR, "confianza.db")

def obtener_conexion():
    os.makedirs(DB_DIR, exist_ok=True)
    return sqlite3.connect(DB_PATH)

conn = obtener_conexion()
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        user_id INTEGER PRIMARY KEY,
        recomendaciones INTEGER DEFAULT 0
    )
''')
conn.commit()
conn.close()

# --- 3. INICIALIZACIÓN DEL BOT ---
class MiBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            print(f"✅ Se sincronizaron {len(synced)} comandos globalmente.")
        except Exception as e:
            print(f"⚠️ Nota de sincronización: {e}")

bot = MiBot()

@bot.event
async def on_ready():
    print(f"🟢 ¡Bot ONLINE exitosamente como: {bot.user.name}!")

# Auxiliar para actualizar roles según cantidad de recomendaciones
async def actualizar_roles_usuario(guild: discord.Guild, usuario: discord.Member, total_recom: int):
    # Si tiene 6 o más recomendaciones, se le asigna/mantiene el nivel máximo (6 = Confiable)
    nivel_efectivo = total_recom
    if nivel_efectivo > 6:
        nivel_efectivo = 6

    nuevo_rol_id = NIVELES_CONFIANZA.get(nivel_efectivo)
    nuevo_rol = guild.get_role(nuevo_rol_id) if nuevo_rol_id else None

    try:
        # Remover otros roles de nivel inferior que el usuario ya no deba tener
        for niv, r_id in NIVELES_CONFIANZA.items():
            if niv != nivel_efectivo:
                rol_antiguo = guild.get_role(r_id)
                if rol_antiguo and rol_antiguo in usuario.roles:
                    await usuario.remove_roles(rol_antiguo)

        # Asignar el rol correspondiente si aún no lo tiene
        if nuevo_rol and nuevo_rol not in usuario.roles:
            await usuario.add_roles(nuevo_rol)

        return nuevo_rol
    except discord.Forbidden:
        return None

# Auxiliar para verificar si es Mod o Admin
def es_mod_o_admin(interaction: discord.Interaction) -> bool:
    es_admin = interaction.user.guild_permissions.administrator
    tiene_rol = any(rol.id == ROL_MODERADOR_ID for rol in interaction.user.roles)
    return es_admin or tiene_rol

# --- 4. COMANDO /recomendar ---
@bot.tree.command(name="recomendar", description="Entrega una recomendación de confianza a un usuario.")
@app_commands.describe(usuario="Jugador al que vas a recomendar", razon="Motivo de la recomendación")
async def recomendar(interaction: discord.Interaction, usuario: discord.Member, razon: str):
    await interaction.response.defer(ephemeral=True)

    if usuario.id == interaction.user.id:
        await interaction.followup.send("❌ No puedes recomendarte a ti mismo.", ephemeral=True)
        return

    if usuario.bot:
        await interaction.followup.send("❌ No puedes recomendar a un bot.", ephemeral=True)
        return

    canal_destino = interaction.guild.get_channel(CANAL_RECOMENDACIONES_ID)
    if not canal_destino:
        await interaction.followup.send("⚠️ No se encontró el canal de recomendaciones configurado.", ephemeral=True)
        return

    user_id_int = int(usuario.id)

    db = obtener_conexion()
    cur = db.cursor()
    
    cur.execute("SELECT recomendaciones FROM usuarios WHERE user_id = ?", (user_id_int,))
    row = cur.fetchone()

    nivel_actual_discord = 0
    for niv, r_id in NIVELES_CONFIANZA.items():
        rol_obj = interaction.guild.get_role(r_id)
        if rol_obj and rol_obj in usuario.roles:
            if niv > nivel_actual_discord:
                nivel_actual_discord = niv

    base_recom = row[0] if row else 0
    if nivel_actual_discord > base_recom:
        base_recom = nivel_actual_discord

    total_recom = base_recom + 1

    cur.execute("INSERT INTO usuarios (user_id, recomendaciones) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET recomendaciones = ?", (user_id_int, total_recom, total_recom))
    db.commit()
    db.close()

    await interaction.followup.send(f"✅ Recomendación enviada con éxito.", ephemeral=True)

    embed = discord.Embed(
        title="🤝 ¡Nueva Recomendación!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Recomendado", value=usuario.mention, inline=True)
    embed.add_field(name="Por", value=interaction.user.mention, inline=True)
    embed.add_field(name="Razón", value=razon, inline=False)
    embed.add_field(name="Total acumulado", value=f"**{total_recom}** recomendaciones", inline=False)

    mensaje_enviado = await canal_destino.send(embed=embed)

    nuevo_rol = await actualizar_roles_usuario(interaction.guild, usuario, total_recom)
    if nuevo_rol and total_recom <= 6:
        await mensaje_enviado.add_reaction("✅")
        await canal_destino.send(
            f"🎉 ¡{usuario.mention} ha subido de nivel! Ahora tiene el rol **{nuevo_rol.name}**."
        )

# --- 5. COMANDO /deshacer ---
@bot.tree.command(name="deshacer", description="Deshace la última recomendación recibida por un usuario.")
@app_commands.describe(usuario="Usuario al que se le revertirá la recomendación")
async def deshacer(interaction: discord.Interaction, usuario: discord.Member):
    if not es_mod_o_admin(interaction):
        await interaction.response.send_message("❌ No tienes el rol necesario para usar este comando.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    user_id_int = int(usuario.id)

    db = obtener_conexion()
    cur = db.cursor()
    cur.execute("SELECT recomendaciones FROM usuarios WHERE user_id = ?", (user_id_int,))
    row = cur.fetchone()

    total_actual = row[0] if row else 0

    if total_actual <= 0:
        db.close()
        await interaction.followup.send(f"⚠️ {usuario.mention} no tiene recomendaciones acumuladas para deshacer.", ephemeral=True)
        return

    nuevo_total = total_actual - 1

    cur.execute("INSERT INTO usuarios (user_id, recomendaciones) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET recomendaciones = ?", (user_id_int, nuevo_total, nuevo_total))
    db.commit()
    db.close()

    nuevo_rol = await actualizar_roles_usuario(interaction.guild, usuario, nuevo_total)

    msg = f"↩️ Se deshizo la última recomendación de {usuario.mention}.\n**Recomendaciones anteriores:** {total_actual} ➔ **Actuales:** {nuevo_total}."
    if nuevo_rol:
        msg += f"\n🎭 Su rol actual es **{nuevo_rol.name}**."

    await interaction.followup.send(msg, ephemeral=True)

# --- 6. COMANDO /quitarrecom ---
@bot.tree.command(name="quitarrecom", description="Resta 1 recomendación a un usuario.")
@app_commands.describe(usuario="Usuario al que se le quitará la recomendación", razon="Motivo del descuento")
async def quitarrecom(interaction: discord.Interaction, usuario: discord.Member, razon: str):
    if not es_mod_o_admin(interaction):
        await interaction.response.send_message("❌ No tienes el rol necesario para usar este comando.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    user_id_int = int(usuario.id)

    db = obtener_conexion()
    cur = db.cursor()
    cur.execute("SELECT recomendaciones FROM usuarios WHERE user_id = ?", (user_id_int,))
    row = cur.fetchone()

    total_actual = row[0] if row else 0

    if total_actual <= 0:
        db.close()
        await interaction.followup.send(f"⚠️ {usuario.mention} ya tiene 0 recomendaciones.", ephemeral=True)
        return

    nuevo_total = total_actual - 1

    cur.execute("INSERT INTO usuarios (user_id, recomendaciones) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET recomendaciones = ?", (user_id_int, nuevo_total, nuevo_total))
    db.commit()
    db.close()

    nuevo_rol = await actualizar_roles_usuario(interaction.guild, usuario, nuevo_total)

    msg = f"📉 Se le restó 1 recomendación a {usuario.mention}. **Total actual:** {nuevo_total}."
    if razon:
        msg += f"\n**Razón:** {razon}"
    if nuevo_rol:
        msg += f"\n🎭 Su rol actual es **{nuevo_rol.name}**."

    await interaction.followup.send(msg, ephemeral=True)

# --- 7. COMANDO /setrecom ---
@bot.tree.command(name="setrecom", description="Establece manualmente las recomendaciones de un usuario.")
@app_commands.describe(usuario="Usuario a corregir", cantidad="Número exacto de recomendaciones")
async def setrecom(interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
    if not es_mod_o_admin(interaction):
        await interaction.response.send_message("❌ No tienes el rol necesario para usar este comando.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    user_id_int = int(usuario.id)

    db = obtener_conexion()
    cur = db.cursor()
    cur.execute("INSERT INTO usuarios (user_id, recomendaciones) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET recomendaciones = ?", (user_id_int, cantidad, cantidad))
    db.commit()
    db.close()

    nuevo_rol = await actualizar_roles_usuario(interaction.guild, usuario, cantidad)

    msg = f"✅ Se actualizaron las recomendaciones de {usuario.mention} a **{cantidad}**."
    if nuevo_rol:
        msg += f" Se le asignó el rol **{nuevo_rol.name}**."
    
    await interaction.followup.send(msg, ephemeral=True)

# --- 8. EJECUCIÓN ---
TOKEN = os.getenv("TOKEN")
bot.run(TOKEN)
