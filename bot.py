
import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands

# --- 1. CONFIGURACIÓN DE ROLES Y CANAL ---
CANAL_RECOMENDACIONES_ID = 1517311566591168562  # ID de tu canal de recomendaciones

NIVELES_CONFIANZA = {
    1: 1518773836156244058,  # ID Rol Nivel 1
    2: 1518773940766380264,  # ID Rol Nivel 2
    3: 1518774004784173066,  # ID Rol Nivel 3
    4: 1518774055229194486,  # ID Rol Nivel 4
    5: 1518774106995032125,  # ID Rol Nivel 5
    6: 1516144475494158480   # ID Rol Confiable (Nivel 6)
}

# --- 2. BASE DE DATOS LOCAL ---
def obtener_conexion():
    return sqlite3.connect("confianza.db")

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

# --- 3. INICIALIZACIÓN DEL BOT (INTENTS ESTÁNDAR SIN FORMULARIO) ---
class MiBot(discord.Client):
    def __init__(self):
        # Intents estándar para evitar formularios de verificación
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = MiBot()

@bot.event
async def on_ready():
    print(f"Bot conectado y listo como: {bot.user.name}")

# --- 4. COMANDO /recomendar SEGURO Y ANTI-DUPLICADOS ---
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

    # Operación de lectura y escritura limpia en SQLite
    db = obtener_conexion()
    cur = db.cursor()
    
    cur.execute("SELECT recomendaciones FROM usuarios WHERE user_id = ?", (usuario.id,))
    row = cur.fetchone()

    if row is None:
        total_recom = 1
        cur.execute("INSERT INTO usuarios (user_id, recomendaciones) VALUES (?, ?)", (usuario.id, 1))
    else:
        total_recom = row[0] + 1
        cur.execute("UPDATE usuarios SET recomendaciones = ? WHERE user_id = ?", (total_recom, usuario.id))
    
    db.commit()
    db.close()

    await interaction.followup.send(f"✅ Recomendación enviada con éxito.", ephemeral=True)

    # Crear la tarjeta informativa
    embed = discord.Embed(
        title="🤝 ¡Nueva Recomendación!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Recomendado", value=usuario.mention, inline=True)
    embed.add_field(name="Por", value=interaction.user.mention, inline=True)
    embed.add_field(name="Razón", value=razon, inline=False)
    embed.add_field(name="Total acumulado", value=f"**{total_recom}** recomendaciones", inline=False)

    mensaje_enviado = await canal_destino.send(embed=embed)

    # Lógica de subida de roles
    if total_recom in NIVELES_CONFIANZA:
        nuevo_rol_id = NIVELES_CONFIANZA[total_recom]
        nuevo_rol = interaction.guild.get_role(nuevo_rol_id)

        if nuevo_rol:
            try:
                # Quitar roles anteriores
                for rol_id in NIVELES_CONFIANZA.values():
                    rol_antiguo = interaction.guild.get_role(rol_id)
                    if rol_antiguo and rol_antiguo in usuario.roles:
                        await usuario.remove_roles(rol_antiguo)

                # Asignar nuevo rol
                await usuario.add_roles(nuevo_rol)
                await mensaje_enviado.add_reaction("✅")

                await canal_destino.send(
                    f"🎉 ¡{usuario.mention} ha subido de nivel! Ahora tiene el rol **{nuevo_rol.name}**."
                )
            except discord.Forbidden:
                await canal_destino.send(
                    "⚠️ El bot no tiene permisos suficientes para modificar roles. Revisa la jerarquía de roles en tu servidor."
                )

# --- 5. EJECUCIÓN (SIEMPRE AL FINAL) ---
TOKEN = os.getenv("TOKEN")
bot.run(TOKEN)
