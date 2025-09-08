import discord
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
from utils.helpers import format_ping, get_role_emoji, get_job_emoji, create_embed_template

logger = logging.getLogger(__name__)

class NotificationManager:
    """Manage player join/leave notifications"""
    
    def __init__(self, bot):
        self.bot = bot
        self.previous_players: Set[str] = set()
        self.player_join_times: Dict[str, datetime] = {}
        
    async def check_player_changes(self, current_players_data: List[Dict[str, Any]]):
        """Check for player join/leave events and send notifications"""
        try:
            # Extract current player names
            current_players = {player.get('name') for player in current_players_data if player.get('name')}
            
            # Find players who joined
            joined_players = current_players - self.previous_players
            
            # Find players who left
            left_players = self.previous_players - current_players
            
            # Process joins
            for player_name in joined_players:
                await self._handle_player_join(player_name, current_players_data)
            
            # Process leaves
            for player_name in left_players:
                await self._handle_player_leave(player_name)
            
            # Update tracking
            self.previous_players = current_players.copy()
            
            # Update join times for current players
            current_time = datetime.now()
            for player_name in current_players:
                if player_name not in self.player_join_times:
                    self.player_join_times[player_name] = current_time
            
            # Remove join times for players who left
            for player_name in left_players:
                self.player_join_times.pop(player_name, None)
                
        except Exception as e:
            logger.error(f"Error checking player changes: {e}")
    
    async def _handle_player_join(self, player_name: str, players_data: List[Dict[str, Any]]):
        """Handle player join event"""
        try:
            # Find player data
            player_data = None
            for player in players_data:
                if player.get('name') == player_name:
                    player_data = player
                    break
            
            if not player_data:
                return
            
            # Log event to database
            await self.bot.db_manager.log_event('join', player_name, {
                'ping': player_data.get('ping', 0),
                'identifiers': player_data.get('identifiers', [])
            })
            
            # Send notification
            embed = await self._create_join_embed(player_name, player_data)
            await self._send_notification(embed)
            
            logger.info(f"Player joined: {player_name}")
            
        except Exception as e:
            logger.error(f"Error handling player join for {player_name}: {e}")
    
    async def _handle_player_leave(self, player_name: str):
        """Handle player leave event"""
        try:
            # Calculate session duration
            session_duration = 0
            if player_name in self.player_join_times:
                join_time = self.player_join_times[player_name]
                session_duration = (datetime.now() - join_time).total_seconds()
            
            # Get player data from database for additional info
            player_db_data = await self.bot.db_manager.get_player(player_name)
            
            # Log event to database
            await self.bot.db_manager.log_event('leave', player_name, {
                'session_duration': session_duration
            })
            
            # Send notification
            embed = await self._create_leave_embed(player_name, session_duration, player_db_data)
            await self._send_notification(embed)
            
            logger.info(f"Player left: {player_name}")
            
        except Exception as e:
            logger.error(f"Error handling player leave for {player_name}: {e}")
    
    async def _create_join_embed(self, player_name: str, player_data: Dict[str, Any]) -> discord.Embed:
        """Create embed for player join notification"""
        try:
            embed = discord.Embed(
                title="🟢 Player Joined",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            ping = player_data.get('ping', 0)
            
            # Get player info from database
            db_player = await self.bot.db_manager.get_player(player_name)
            
            embed.add_field(
                name="👤 Player",
                value=f"**{player_name}**",
                inline=True
            )
            
            embed.add_field(
                name="🏓 Ping",
                value=format_ping(ping),
                inline=True
            )
            
            embed.add_field(
                name="🕐 Time",
                value=f"<t:{int(datetime.now().timestamp())}:T>",
                inline=True
            )
            
            # Add role and job if available from database
            if db_player:
                role = db_player.get('role', 'civilian')
                job = db_player.get('job', 'unemployed')
                
                embed.add_field(
                    name="👤 Role",
                    value=f"{get_role_emoji(role)} {role.title()}",
                    inline=True
                )
                
                embed.add_field(
                    name="💼 Job",
                    value=f"{get_job_emoji(job)} {job.title()}",
                    inline=True
                )
                
                # Add playtime if available
                playtime = db_player.get('playtime', 0)
                if playtime > 0:
                    from utils.helpers import format_playtime
                    embed.add_field(
                        name="⏰ Total Playtime",
                        value=format_playtime(playtime),
                        inline=True
                    )
            
            embed.set_footer(text="Motionlife Roleplay")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating join embed: {e}")
            return create_embed_template("🟢 Player Joined", discord.Color.green())
    
    async def _create_leave_embed(self, player_name: str, session_duration: float, player_db_data: Dict[str, Any] = None) -> discord.Embed:
        """Create embed for player leave notification"""
        try:
            embed = discord.Embed(
                title="🔴 Player Left",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="👤 Player",
                value=f"**{player_name}**",
                inline=True
            )
            
            # Format session duration
            if session_duration > 0:
                from utils.helpers import format_playtime
                embed.add_field(
                    name="⏱️ Session Duration",
                    value=format_playtime(int(session_duration)),
                    inline=True
                )
            
            embed.add_field(
                name="🕐 Time",
                value=f"<t:{int(datetime.now().timestamp())}:T>",
                inline=True
            )
            
            # Add additional info if available
            if player_db_data:
                role = player_db_data.get('role', 'civilian')
                job = player_db_data.get('job', 'unemployed')
                
                embed.add_field(
                    name="👤 Role",
                    value=f"{get_role_emoji(role)} {role.title()}",
                    inline=True
                )
                
                embed.add_field(
                    name="💼 Job",
                    value=f"{get_job_emoji(job)} {job.title()}",
                    inline=True
                )
                
                # Add total playtime
                playtime = player_db_data.get('playtime', 0)
                if playtime > 0:
                    from utils.helpers import format_playtime
                    embed.add_field(
                        name="⏰ Total Playtime",
                        value=format_playtime(playtime),
                        inline=True
                    )
            
            embed.set_footer(text="Motionlife Roleplay")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating leave embed: {e}")
            return create_embed_template("🔴 Player Left", discord.Color.red())
    
    async def _send_notification(self, embed: discord.Embed):
        """Send notification to designated channel"""
        try:
            if not self.bot.config.NOTIFICATIONS_CHANNEL_ID:
                return
            
            channel = self.bot.get_channel(self.bot.config.NOTIFICATIONS_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)
            else:
                logger.warning(f"Notification channel {self.bot.config.NOTIFICATIONS_CHANNEL_ID} not found")
                
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    async def send_server_status_notification(self, status: str, details: Dict[str, Any] = None):
        """Send server status notifications"""
        try:
            if not self.bot.config.NOTIFICATIONS_CHANNEL_ID:
                return
            
            channel = self.bot.get_channel(self.bot.config.NOTIFICATIONS_CHANNEL_ID)
            if not channel:
                return
            
            if status == "online":
                embed = discord.Embed(
                    title="🟢 Server Online",
                    description="The server is now online and accepting connections.",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                
                if details:
                    embed.add_field(
                        name="👥 Players",
                        value=f"{details.get('clients', 0)}/{details.get('maxClients', 128)}",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="🏓 Ping",
                        value=f"{details.get('ping', 0):.0f}ms",
                        inline=True
                    )
                
            elif status == "offline":
                embed = discord.Embed(
                    title="🔴 Server Offline",
                    description="The server is currently offline or unreachable.",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                
            elif status == "maintenance":
                embed = discord.Embed(
                    title="⚙️ Server Maintenance",
                    description="The server is in maintenance mode with low player count.",
                    color=discord.Color.orange(),
                    timestamp=datetime.now()
                )
                
                if details:
                    embed.add_field(
                        name="👥 Players",
                        value=f"{details.get('clients', 0)}/{details.get('maxClients', 0)}",
                        inline=True
                    )
            
            else:
                return  # Unknown status
            
            embed.set_footer(text="Motionlife Roleplay")
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending server status notification: {e}")
    
    async def send_milestone_notification(self, milestone_type: str, player_name: str, value: Any):
        """Send milestone achievement notifications"""
        try:
            if not self.bot.config.NOTIFICATIONS_CHANNEL_ID:
                return
            
            channel = self.bot.get_channel(self.bot.config.NOTIFICATIONS_CHANNEL_ID)
            if not channel:
                return
            
            embed = discord.Embed(
                title="🎉 Milestone Achievement!",
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            
            if milestone_type == "playtime_hours":
                embed.description = f"**{player_name}** has reached **{value} hours** of playtime!"
                embed.add_field(
                    name="🏆 Achievement",
                    value=f"{value} Hour Club",
                    inline=True
                )
                
            elif milestone_type == "sessions":
                embed.description = f"**{player_name}** has completed **{value}** sessions on the server!"
                embed.add_field(
                    name="🏆 Achievement",
                    value=f"{value} Sessions Milestone",
                    inline=True
                )
            
            embed.set_footer(text="Motionlife Roleplay")
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error sending milestone notification: {e}")
    
    async def create_player_summary_embed(self, period_hours: int = 24) -> discord.Embed:
        """Create daily/periodic player activity summary"""
        try:
            embed = discord.Embed(
                title=f"📊 Player Activity Summary ({period_hours}h)",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Get recent events
            recent_events = await self.bot.db_manager.get_recent_events(limit=100)
            
            # Filter events by time period
            cutoff_time = datetime.now() - timedelta(hours=period_hours)
            period_events = [
                event for event in recent_events 
                if event.get('timestamp', datetime.min) >= cutoff_time
            ]
            
            # Count joins and leaves
            joins = [e for e in period_events if e.get('event_type') == 'join']
            leaves = [e for e in period_events if e.get('event_type') == 'leave']
            
            # Get unique players
            unique_players = set()
            for event in period_events:
                unique_players.add(event.get('player_name'))
            
            embed.add_field(
                name="👥 Unique Players",
                value=str(len(unique_players)),
                inline=True
            )
            
            embed.add_field(
                name="🟢 Total Joins",
                value=str(len(joins)),
                inline=True
            )
            
            embed.add_field(
                name="🔴 Total Leaves",
                value=str(len(leaves)),
                inline=True
            )
            
            # Most active players
            player_activity = {}
            for event in period_events:
                player_name = event.get('player_name')
                if player_name:
                    player_activity[player_name] = player_activity.get(player_name, 0) + 1
            
            if player_activity:
                top_active = sorted(player_activity.items(), key=lambda x: x[1], reverse=True)[:5]
                active_text = "\n".join([f"• **{name}**: {count} events" for name, count in top_active])
                
                embed.add_field(
                    name="🔥 Most Active Players",
                    value=active_text,
                    inline=False
                )
            
            embed.set_footer(text="Motionlife Roleplay")
            return embed
            
        except Exception as e:
            logger.error(f"Error creating player summary embed: {e}")
            return create_embed_template("📊 Player Activity Summary", discord.Color.blue())
    
    async def send_daily_summary(self):
        """Send daily player activity summary"""
        try:
            embed = await self.create_player_summary_embed(24)
            await self._send_notification(embed)
            
        except Exception as e:
            logger.error(f"Error sending daily summary: {e}")
    
    def get_current_online_players(self) -> List[str]:
        """Get list of currently online players"""
        return list(self.previous_players)
    
    def is_player_online(self, player_name: str) -> bool:
        """Check if a specific player is currently online"""
        return player_name in self.previous_players
    
    async def send_custom_notification(self, title: str, description: str, color: discord.Color = discord.Color.blue(), fields: List[Dict[str, Any]] = None):
        """Send custom notification"""
        try:
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.now()
            )
            
            if fields:
                for field in fields:
                    embed.add_field(
                        name=field.get('name', 'Field'),
                        value=field.get('value', 'Value'),
                        inline=field.get('inline', True)
                    )
            
            embed.set_footer(text="Motionlife Roleplay")
            await self._send_notification(embed)
            
        except Exception as e:
            logger.error(f"Error sending custom notification: {e}")
