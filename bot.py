import discord
from discord.ext import commands, tasks
import asyncio
import os
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone
import json

from services.fivem_api import FiveMAPI
from services.database import DatabaseManager
from services.analytics import AnalyticsManager
from services.leaderboard import LeaderboardManager
from services.notifications import NotificationManager
from utils.config import Config
from utils.helpers import format_playtime, format_ping

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('motionlife_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MotionlifeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        # Initialize services
        self.config = Config()
        # Use robust FiveM API with longer timeout
        self.fivem_api = FiveMAPI("http://main.motionliferp.com:30120", timeout=15)
        self.db_manager = None
        self.analytics_manager = None
        self.leaderboard_manager = None
        self.notification_manager = None
        
        # Bot state
        self.server_status = {
            'online': False,
            'hostname': '',
            'clients': 0,
            'maxClients': 0,
            'ping': 0
        }
        self.players_data = []
        self.presence_rotation_index = 0
        self.last_server_online = False
        
    async def setup_hook(self):
        """Initialize bot services and tasks"""
        try:
            # Initialize database and services
            self.db_manager = DatabaseManager(self.config.MONGODB_URI)
            await self.db_manager.connect()
            
            self.analytics_manager = AnalyticsManager(self.db_manager)
            self.leaderboard_manager = LeaderboardManager(self.db_manager)
            self.notification_manager = NotificationManager(self)
            
            # Test FiveM API connection
            connection_test = await self.fivem_api.test_connection()
            logger.info(f"FiveM API connection test: {connection_test}")
            
            # Start background tasks
            self.update_server_status.start()
            self.update_leaderboard.start()
            self.cleanup_task.start()
            
            logger.info("Bot setup completed successfully")
            
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
    
    async def on_ready(self):
        """Bot ready event"""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Load slash commands
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
        
        # Start presence updates only after bot is ready
        if not self.update_presence.is_running():
            self.update_presence.start()
            logger.info("Started presence update task")
    
    @tasks.loop(seconds=30)  # Update every 30 seconds
    async def update_server_status(self):
        """Update server status from FiveM API"""
        try:
            # Get comprehensive server data
            server_data = await self.fivem_api.get_comprehensive_server_data()
            
            if server_data and server_data.get('online', False):
                self.server_status.update(server_data)
                
                # Get players data  
                players_data = server_data.get('players', [])
                if players_data:
                    self.players_data = players_data
                    
                    # Update analytics with current players
                    await self.analytics_manager.update_player_data(players_data)
                    
                    # Log ping data
                    await self.analytics_manager.log_ping_data(
                        self.server_status.get('ping', 0)
                    )
                    
                    # Check for player join/leave notifications
                    await self.notification_manager.check_player_changes(players_data)
                
                # Check if server just came online
                if not self.last_server_online:
                    await self.notification_manager.send_server_status_notification(
                        "online", self.server_status
                    )
                    logger.info("Server came online")
                
                self.last_server_online = True
                
            else:
                # Server is offline
                self.server_status.update({
                    'online': False,
                    'hostname': 'Motionlife Roleplay',
                    'clients': 0,
                    'maxClients': 0,
                    'ping': 0
                })
                self.players_data = []
                
                # Check if server just went offline
                if self.last_server_online:
                    await self.notification_manager.send_server_status_notification("offline")
                    logger.warning("Server went offline")
                
                self.last_server_online = False
                
        except Exception as e:
            logger.error(f"Error updating server status: {e}")
            # Set server as offline on error
            self.server_status['online'] = False
            if self.last_server_online:
                await self.notification_manager.send_server_status_notification("offline")
                self.last_server_online = False
    
    @tasks.loop(seconds=10)
    async def update_presence(self):
        """Update bot presence with server info"""
        try:
            # Wait for bot to be ready
            if not self.is_ready():
                return
                
            if not self.server_status['online']:
                await self.change_presence(
                    status=discord.Status.dnd,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name="🔴 Server Offline"
                    )
                )
                return
            
            clients = self.server_status.get('clients', 0)
            max_clients = self.server_status.get('maxClients', 128)
            
            if clients < 5:  # Low player count
                await self.change_presence(
                    status=discord.Status.idle,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f"⚙️ {clients}/{max_clients} Players"
                    )
                )
                return
            
            # Rotating presence messages for active server
            presence_messages = await self._get_presence_messages()
            if presence_messages:
                message = presence_messages[self.presence_rotation_index % len(presence_messages)]
                
                await self.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name=message
                    )
                )
                
                self.presence_rotation_index += 1
                
        except Exception as e:
            logger.error(f"Error updating presence: {e}")
    
    @tasks.loop(minutes=5)
    async def update_leaderboard(self):
        """Update leaderboard in designated channel"""
        try:
            if self.config.LEADERBOARD_CHANNEL_ID:
                channel = self.get_channel(self.config.LEADERBOARD_CHANNEL_ID)
                if channel:
                    await self.leaderboard_manager.update_leaderboard_message(channel)
                    logger.debug("Updated leaderboard")
        except Exception as e:
            logger.error(f"Error updating leaderboard: {e}")
    
    @tasks.loop(hours=1)  # Run cleanup every hour
    async def cleanup_task(self):
        """Periodic cleanup tasks"""
        try:
            # Clean offline players from analytics tracking
            await self.analytics_manager.clean_offline_players()
            
            # Clean old database records (daily at midnight)
            current_hour = datetime.now().hour
            if current_hour == 0:  # Midnight UTC
                await self.db_manager.cleanup_old_data()
                logger.info("Performed daily database cleanup")
                
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
    
    async def _get_presence_messages(self):
        """Generate rotating presence messages"""
        try:
            messages = []
            
            # Basic server info
            hostname = self.server_status.get('hostname', 'Motionlife Roleplay')
            clients = self.server_status.get('clients', 0)
            max_clients = self.server_status.get('maxClients', 0)
            
            messages.append(f"{clients}/{max_clients} Players On {hostname}")
            
            # Ping statistics
            if hasattr(self.analytics_manager, 'get_ping_stats'):
                ping_stats = await self.analytics_manager.get_ping_stats(hours=1)
                if ping_stats:
                    messages.append(
                        f"Ping: {ping_stats['low']}ms - {ping_stats['high']}ms"
                    )
            
            # Top players
            if hasattr(self.leaderboard_manager, 'get_top_players'):
                top_players = await self.leaderboard_manager.get_top_players(limit=3)
                if top_players:
                    top_names = [player.get('name', 'Unknown')[:15] for player in top_players]
                    messages.append(f"Top Players: {', '.join(top_names)}")
            
            # Current session stats
            if hasattr(self.analytics_manager, 'get_session_statistics'):
                session_stats = await self.analytics_manager.get_session_statistics()
                if session_stats.get('total_online', 0) > 0:
                    avg_session = session_stats.get('average_session_time', 0)
                    if avg_session > 60:  # More than 1 minute
                        messages.append(f"Avg Session: {format_playtime(avg_session)}")
            
            return messages if messages else ["Motionlife Roleplay"]
            
        except Exception as e:
            logger.error(f"Error generating presence messages: {e}")
            return ["Motionlife Roleplay"]

# Slash Commands
@discord.app_commands.describe(name="Player name to lookup")
async def player_info(interaction: discord.Interaction, name: str):
    """Get detailed player information"""
    try:
        bot = interaction.client
        
        # Search for player (partial match)
        players = await bot.db_manager.get_player_search(name, limit=1)
        
        if not players:
            await interaction.response.send_message(
                f"❌ Player `{name}` not found in database.",
                ephemeral=True
            )
            return
        
        player_data = players[0]
        player_name = player_data.get('name', 'Unknown')
        
        # Get comprehensive player info
        detailed_info = await bot.analytics_manager.get_player_info(player_name)
        
        if not detailed_info:
            await interaction.response.send_message(
                f"❌ Could not retrieve detailed information for `{player_name}`.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=f"👤 Player Info: {player_name}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Basic info
        embed.add_field(
            name="⏰ Total Playtime",
            value=format_playtime(detailed_info.get('playtime', 0)),
            inline=True
        )
        
        embed.add_field(
            name="📊 Total Sessions",
            value=str(detailed_info.get('total_sessions', 0)),
            inline=True
        )
        
        embed.add_field(
            name="🏓 Average Ping",
            value=f"{detailed_info.get('avg_ping', 0):.0f}ms",
            inline=True
        )
        
        # Role and job info
        role = detailed_info.get('role', 'civilian')
        job = detailed_info.get('job', 'unemployed')
        
        embed.add_field(
            name="👤 Role",
            value=f"{role.title()}",
            inline=True
        )
        
        embed.add_field(
            name="💼 Job", 
            value=f"{job.title()}",
            inline=True
        )
        
        # Online status
        is_online = detailed_info.get('is_online', False)
        if is_online:
            current_session = detailed_info.get('current_session_duration', 0)
            embed.add_field(
                name="🟢 Status",
                value=f"Online ({format_playtime(current_session)})",
                inline=True
            )
        else:
            last_seen = detailed_info.get('lastSeen')
            if last_seen:
                embed.add_field(
                    name="🔴 Last Seen",
                    value=f"<t:{int(last_seen.timestamp())}:R>",
                    inline=True
                )
        
        # Recent activity
        recent_events = detailed_info.get('recent_events', [])
        if recent_events:
            event_text = []
            for event in recent_events[:3]:  # Last 3 events
                event_type = event.get('event_type', 'unknown')
                event_time = event.get('timestamp')
                if event_time:
                    time_str = f"<t:{int(event_time.timestamp())}:R>"
                    event_text.append(f"{event_type.title()}: {time_str}")
            
            if event_text:
                embed.add_field(
                    name="📅 Recent Activity",
                    value="\n".join(event_text),
                    inline=False
                )
        
        embed.set_footer(text="Motionlife Roleplay")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in player_info command: {e}")
        await interaction.response.send_message(
            "❌ Error retrieving player information.",
            ephemeral=True
        )

@discord.app_commands.describe()
async def server_ping(interaction: discord.Interaction):
    """Show server ping statistics"""
    try:
        bot = interaction.client
        ping_stats = await bot.analytics_manager.get_ping_stats(hours=24)
        
        if not ping_stats:
            await interaction.response.send_message(
                "❌ No ping data available.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="📊 Server Ping Statistics (24h)",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="🟢 Low Ping",
            value=f"{ping_stats['low']}ms",
            inline=True
        )
        
        embed.add_field(
            name="🟡 Average Ping",
            value=f"{ping_stats['avg']}ms",
            inline=True
        )
        
        embed.add_field(
            name="🔴 High Ping",
            value=f"{ping_stats['high']}ms",
            inline=True
        )
        
        # Add current server status
        if bot.server_status['online']:
            embed.add_field(
                name="🌐 Current Server Ping",
                value=f"{bot.server_status.get('ping', 0):.1f}ms",
                inline=True
            )
            
            embed.add_field(
                name="👥 Players Online",
                value=f"{bot.server_status.get('clients', 0)}/{bot.server_status.get('maxClients', 128)}",
                inline=True
            )
        
        embed.set_footer(text="Motionlife Roleplay")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in server_ping command: {e}")
        await interaction.response.send_message(
            "❌ Error retrieving ping statistics.",
            ephemeral=True
        )

@discord.app_commands.describe()
async def server_stats(interaction: discord.Interaction):
    """Show comprehensive server statistics with graph"""
    try:
        bot = interaction.client
        
        # Defer response for longer processing
        await interaction.response.defer()
        
        # Get statistics
        stats = await bot.analytics_manager.get_server_stats(days=7)
        
        if not stats:
            await interaction.followup.send("❌ No statistics data available.")
            return
        
        # Create embed
        embed = discord.Embed(
            title="📈 Server Statistics (Last 7 Days)",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="👥 Peak Players",
            value=f"{stats.get('peak_players', 0)} players",
            inline=True
        )
        
        embed.add_field(
            name="🔄 Current Online",
            value=f"{stats.get('current_players', 0)} players",
            inline=True
        )
        
        embed.add_field(
            name="📊 Average Players",
            value=f"{stats.get('avg_players', 0):.1f} players",
            inline=True
        )
        
        embed.add_field(
            name="🏓 Average Ping",
            value=f"{stats.get('avg_ping', 0):.1f}ms",
            inline=True
        )
        
        embed.add_field(
            name="⏰ Total Playtime",
            value=format_playtime(stats.get('total_playtime', 0)),
            inline=True
        )
        
        embed.add_field(
            name="🎯 Active Players (24h)",
            value=f"{stats.get('active_players', 0)} players",
            inline=True
        )
        
        embed.add_field(
            name="🔄 Server Uptime",
            value=f"{stats.get('uptime_percentage', 0):.1f}%",
            inline=True
        )
        
        # Generate graph
        try:
            graph_path = await bot.analytics_manager.generate_stats_graph()
            if graph_path and os.path.exists(graph_path):
                file = discord.File(graph_path, filename="server_stats.png")
                embed.set_image(url="attachment://server_stats.png")
                await interaction.followup.send(embed=embed, file=file)
                
                # Clean up
                try:
                    os.remove(graph_path)
                except:
                    pass
            else:
                await interaction.followup.send(embed=embed)
        except Exception as graph_error:
            logger.warning(f"Could not generate graph: {graph_error}")
            await interaction.followup.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in server_stats command: {e}")
        await interaction.followup.send("❌ Error generating server statistics.")

@discord.app_commands.describe()
async def online_players(interaction: discord.Interaction):
    """Show currently online players"""
    try:
        bot = interaction.client
        
        if not bot.server_status['online']:
            await interaction.response.send_message(
                "❌ Server is currently offline.",
                ephemeral=True
            )
            return
        
        online_players = await bot.analytics_manager.get_current_online_players()
        
        if not online_players:
            await interaction.response.send_message(
                "👥 No players currently online.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=f"👥 Online Players ({len(online_players)}/{bot.server_status.get('maxClients', 128)})",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        # Sort by session duration (longest first)
        online_players.sort(key=lambda x: x.get('session_duration', 0), reverse=True)
        
        player_list = []
        for i, player in enumerate(online_players[:20]):  # Limit to 20 players
            name = player.get('name', 'Unknown')
            ping = player.get('ping', 0)
            session_time = format_playtime(player.get('session_duration', 0))
            
            player_list.append(
                f"{i+1:2d}. **{name}** - {format_ping(ping)} - {session_time}"
            )
        
        if player_list:
            # Split into chunks if too long
            chunk_size = 20
            for i in range(0, len(player_list), chunk_size):
                chunk = player_list[i:i + chunk_size]
                embed.add_field(
                    name=f"Players {i+1}-{i+len(chunk)}" if i > 0 else "Players",
                    value="\n".join(chunk),
                    inline=False
                )
        
        # Add summary stats
        total_session_time = sum(p.get('session_duration', 0) for p in online_players)
        avg_session_time = total_session_time / len(online_players) if online_players else 0
        avg_ping = sum(p.get('ping', 0) for p in online_players if p.get('ping', 0) > 0)
        avg_ping = avg_ping / len([p for p in online_players if p.get('ping', 0) > 0]) if online_players else 0
        
        embed.add_field(
            name="📊 Statistics",
            value=f"Average Session: {format_playtime(int(avg_session_time))}\n"
                  f"Average Ping: {avg_ping:.0f}ms\n"
                  f"Total Online Time: {format_playtime(int(total_session_time))}",
            inline=False
        )
        
        embed.set_footer(text="Motionlife Roleplay")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in online_players command: {e}")
        await interaction.response.send_message(
            "❌ Error retrieving online players.",
            ephemeral=True
        )

# Add slash commands to bot
async def setup_commands(bot):
    bot.tree.add_command(discord.app_commands.Command(
        name="player_info",
        description="Get detailed information about a player",
        callback=player_info
    ))
    
    bot.tree.add_command(discord.app_commands.Command(
        name="server_ping",
        description="Show server ping statistics",
        callback=server_ping
    ))
    
    bot.tree.add_command(discord.app_commands.Command(
        name="server_stats", 
        description="Show server statistics",
        callback=server_stats
    ))
    
    bot.tree.add_command(discord.app_commands.Command(
        name="online_players",
        description="Show currently online players",
        callback=online_players
    ))

async def main():
    """Main function to run the bot"""
    bot = MotionlifeBot()
    
    # Setup slash commands
    await setup_commands(bot)
    
    try:
        logger.info("Starting Motionlife RP Discord Bot...")
        await bot.start(os.getenv('DISCORD_TOKEN'))
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested by user")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        # Cleanup
        if bot.db_manager:
            await bot.db_manager.close()
        if bot.fivem_api:
            await bot.fivem_api.close()
        logger.info("Bot shutdown completed")

if __name__ == "__main__":
    asyncio.run(main())