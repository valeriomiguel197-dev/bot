import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands

# --- 1. CONFIGURACIÓN DE ROLES, CANAL Y SERVIDOR ---
CANAL_RECOMENDACIONES_ID = 1517311566591168562  # ID de tu canal de recomendaciones
ID_SERVIDOR = 1516144475494158480  # ID de tu servidor de Discord

# ⚠️ REEMPLAZÁ ESTE NÚMERO POR LA ID DEL ROL DE MODERADOR (O EL ROL QUE QUIERAS AUTORIZAR)
ROL_MODERADOR_ID = 123456789012345678  

NIVELES_CONFIANZA = {
    1: 1518773836156244058,  # ID Rol Nivel 1
    2: 1518773940766380264,  # ID Rol Nivel 2
    3: 1518774004784173066,  # ID Rol Nivel 3
    4: 1518774055229194486,  # ID Rol Nivel 4
    5: 1518774106995032125,  # ID Rol Nivel 5
    6: 1516144475494158480   # ID Rol Confiable (Nivel 6)
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
        intents.members = True  # Lectura de miembros requerida
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=ID_SERVIDOR)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("✅ Comandos sincronizados instantáneamente con el servidor.")

bot = MiBot()

@bot.event
async def on_ready():
    print(f"Bot conectado y listo como: {bot.user.name}")

# Auxiliar de asignación de roles
async def actualizar_roles_usuario(guild: discord.Guild, usuario: discord.Member, total_recom: int):
    if total_recom not in NIVELES_CONFIANZA:
        return None

    nuevo_rol_id = NIVELES_CONFIANZA[total_recom]
    nuevo_rol = guild.get_role(nuevo_rol_id)

    if not nuevo_rol:
        return None

    try:
        for r_id in NIVELES_CONFIANZA.values():
            if r_id != nuevo_rol_id:
                rol_antiguo = guild.get_role(r_id)
                if rol_antiguo and rol_antiguo in usuario.roles:
                    await usuario.remove_roles(rol_antiguo)

        if nuevo_rol not in usuario.roles:
            await usuario.add_roles(nuevo_rol)

        return nuevo_rol
    except discord.Forbidden:
        return None

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
    if nuevo_rol:
        await mensaje_enviado.add_reaction("✅")
        await canal_destino.send(
            f"🎉 ¡{usuario.mention} ha subido de nivel! Ahora tiene el rol **{nuevo_rol.name}**."
        )

# --- 5. COMANDO /sincronizar (PERMITIDO A USUARIOS CON EL ROL INDICADO) ---
@bot.tree.command(name="sincronizar", description="Sincroniza la base de datos con los roles actuales del servidor.")
async def sincronizar(interaction: discord.Interaction):
    # Verificar si el usuario tiene el rol autorizado (o si es Administrador por seguridad)
    tiene_rol = any(rol.id == 1516746824961097778 for rol in interaction.user.roles)
    if not tiene_rol and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ No tienes el rol necesario para usar este comando.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    db = obtener_conexion()
    cur = db.cursor()

    actualizados = 0
    for miembro in interaction.guild.members:
        if miembro.bot:
            continue
        
        nivel_encontrado = 0
        for nivel, rol_id in NIVELES_CONFIANZA.items():
            rol = interaction.guild.get_role(rol_id)
            if rol and rol in miembro.roles:
                if nivel > nivel_encontrado:
                    nivel_encontrado = nivel

        if nivel_encontrado > 0:
            user_id_int = int(miembro.id)
            cur.execute(
                "INSERT INTO usuarios (user_id, recomendaciones) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET recomendaciones = ?",
                (user_id_int, nivel_encontrado, nivel_encontrado)
            )
            actualizados += 1

    db.commit()
    db.close()

    await interaction.followup.send(f"✅ ¡Sincronización completa! Se registraron las recomendaciones de **{actualizados}** usuarios según sus roles actuales.", ephemeral=True)

# --- 6. COMANDO /setrecom (PERMITIDO A USUARIOS CON EL ROL INDICADO) ---
@bot.tree.command(name="setrecom", description="Establece manualmente las recomendaciones de un usuario.")
@app_commands.describe(usuario="Usuario a corregir", cantidad="Número exacto de recomendaciones")
async def setrecom(interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
    # Verificar si el usuario tiene el rol autorizado (o si es Administrador)
    tiene_rol = any(rol.id == ROL_MODERADOR_ID for rol in interaction.user.roles)
    if not tiene_rol and not interaction.user.guild_permissions.administrator:
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

# --- 7. EJECUCIÓN ---
TOKEN = os.getenv("TOKEN")
bot.run(TOKEN)
