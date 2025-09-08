import discord
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from services.database import DatabaseManager
from utils.helpers import format_playtime, get_role_emoji, get_job_emoji, create_embed_template

logger = logging.getLogger(__name__)

class LeaderboardManager:
    """Leaderboard Manager for player rankings"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.last_message_id: Optional[int] = None
        self.leaderboard_types = {
            'playtime': 'Top Players by Playtime',
            'sessions': 'Most Active Players',
            'recent': 'Recently Active Players'
        }
    
    async def get_top_players(self, limit: int = 10, category: str = 'playtime') -> List[Dict[str, Any]]:
        """Get top players by specified category"""
        try:
            if category == 'playtime':
                return await self.db.get_players_by_playtime(limit)
            elif category == 'recent':
                return await self._get_recently_active_players(limit)
            else:
                return await self.db.get_players_by_playtime(limit)
                
        except Exception as e:
            logger.error(f"Error getting top players: {e}")
            return []
    
    async def _get_recently_active_players(self, limit: int) -> List[Dict[str, Any]]:
        """Get recently active players"""
        try:
            cursor = self.db.db.players.find({}).sort("lastSeen", -1).limit(limit)
            players = await cursor.to_list(length=limit)
            return players
            
        except Exception as e:
            logger.error(f"Error getting recently active players: {e}")
            return []
    
    async def create_leaderboard_embed(self, category: str = 'playtime', limit: int = 10) -> discord.Embed:
        """Create leaderboard embed"""
        try:
            players = await self.get_top_players(limit, category)
            
            embed = create_embed_template(
                title=f"🏆 {self.leaderboard_types.get(category, 'Leaderboard')}",
                color=discord.Color.gold()
            )
            
            if not players:
                embed.add_field(
                    name="No Data",
                    value="No players found in database.",
                    inline=False
                )
                return embed
            
            # Create leaderboard text
            leaderboard_text = ""
            medals = ["🥇", "🥈", "🥉"]
            
            for i, player in enumerate(players):
                position = i + 1
                
                # Get position emoji
                if position <= 3:
                    position_emoji = medals[i]
                else:
                    position_emoji = f"`{position:2d}.`"
                
                # Format player info based on category
                if category == 'playtime':
                    value = format_playtime(player.get('playtime', 0))
                    extra_info = f"({player.get('totalSessions', 0)} sessions)"
                elif category == 'recent':
                    last_seen = player.get('lastSeen')
                    if last_seen:
                        value = f"<t:{int(last_seen.timestamp())}:R>"
                    else:
                        value = "Unknown"
                    extra_info = format_playtime(player.get('playtime', 0))
                else:
                    value = str(player.get('playtime', 0))
                    extra_info = ""
                
                # Get role and job emojis
                role_emoji = get_role_emoji(player.get('role', 'civilian'))
                job_emoji = get_job_emoji(player.get('job', 'unemployed'))
                
                # Build player line
                player_name = player.get('name', 'Unknown')[:20]  # Limit name length
                
                leaderboard_text += f"{position_emoji} {role_emoji} **{player_name}**\n"
                leaderboard_text += f"    {job_emoji} {value} {extra_info}\n"
                
                # Add separator for top 3
                if position == 3 and len(players) > 3:
                    leaderboard_text += "\n"
            
            embed.add_field(
                name=f"Top {len(players)} Players",
                value=leaderboard_text,
                inline=False
            )
            
            # Add statistics
            if category == 'playtime':
                total_playtime = sum(player.get('playtime', 0) for player in players)
                avg_playtime = total_playtime / len(players) if players else 0
                
                embed.add_field(
                    name="📊 Statistics",
                    value=f"Total Playtime: {format_playtime(total_playtime)}\n"
                          f"Average: {format_playtime(int(avg_playtime))}",
                    inline=True
                )
            
            embed.add_field(
                name="🔄 Last Updated",
                value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:R>",
                inline=True
            )
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating leaderboard embed: {e}")
            
            # Return error embed
            embed = create_embed_template(
                title="❌ Leaderboard Error",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Error",
                value="Failed to load leaderboard data.",
                inline=False
            )
            return embed
    
    async def update_leaderboard_message(self, channel: discord.TextChannel):
        """Update or create leaderboard message in channel"""
        try:
            # Create main leaderboard embed
            main_embed = await self.create_leaderboard_embed('playtime', 10)
            
            # Create additional embeds for different categories
            recent_embed = await self.create_leaderboard_embed('recent', 5)
            recent_embed.title = "🕒 Recently Active Players"
            
            embeds = [main_embed, recent_embed]
            
            # Try to edit existing message or create new one
            if self.last_message_id:
                try:
                    message = await channel.fetch_message(self.last_message_id)
                    await message.edit(embeds=embeds)
                    logger.info("Updated existing leaderboard message")
                    return
                except discord.NotFound:
                    self.last_message_id = None
                except discord.HTTPException as e:
                    logger.warning(f"Failed to edit leaderboard message: {e}")
                    self.last_message_id = None
            
            # Create new message
            message = await channel.send(embeds=embeds)
            self.last_message_id = message.id
            logger.info("Created new leaderboard message")
            
        except Exception as e:
            logger.error(f"Error updating leaderboard message: {e}")
    
    async def create_player_rank_embed(self, player_name: str) -> Optional[discord.Embed]:
        """Create individual player rank information"""
        try:
            # Get player data
            player = await self.db.get_player(player_name)
            if not player:
                return None
            
            # Get all players sorted by playtime to find rank
            all_players = await self.db.get_players_by_playtime(limit=1000)
            
            player_rank = None
            for i, p in enumerate(all_players):
                if p.get('name') == player_name:
                    player_rank = i + 1
                    break
            
            embed = create_embed_template(
                title=f"📊 Player Rank: {player_name}",
                color=discord.Color.blue()
            )
            
            # Basic stats
            embed.add_field(
                name="🏆 Rank",
                value=f"#{player_rank}" if player_rank else "Unranked",
                inline=True
            )
            
            embed.add_field(
                name="⏰ Playtime",
                value=format_playtime(player.get('playtime', 0)),
                inline=True
            )
            
            embed.add_field(
                name="📊 Sessions",
                value=str(player.get('totalSessions', 0)),
                inline=True
            )
            
            # Role and job
            role_emoji = get_role_emoji(player.get('role', 'civilian'))
            job_emoji = get_job_emoji(player.get('job', 'unemployed'))
            
            embed.add_field(
                name="👤 Role",
                value=f"{role_emoji} {player.get('role', 'Civilian').title()}",
                inline=True
            )
            
            embed.add_field(
                name="💼 Job",
                value=f"{job_emoji} {player.get('job', 'Unemployed').title()}",
                inline=True
            )
            
            embed.add_field(
                name="📅 Last Seen",
                value=f"<t:{int(player.get('lastSeen', datetime.utcnow()).timestamp())}:R>",
                inline=True
            )
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating player rank embed: {e}")
            return None
    
    async def get_player_comparison(self, player1: str, player2: str) -> Optional[discord.Embed]:
        """Create player comparison embed"""
        try:
            p1_data = await self.db.get_player(player1)
            p2_data = await self.db.get_player(player2)
            
            if not p1_data or not p2_data:
                return None
            
            embed = create_embed_template(
                title="⚔️ Player Comparison",
                color=discord.Color.purple()
            )
            
            # Compare playtime
            p1_playtime = p1_data.get('playtime', 0)
            p2_playtime = p2_data.get('playtime', 0)
            
            embed.add_field(
                name=f"⏰ Playtime",
                value=f"**{player1}:** {format_playtime(p1_playtime)}\n"
                      f"**{player2}:** {format_playtime(p2_playtime)}",
                inline=False
            )
            
            # Compare roles and jobs
            embed.add_field(
                name="👤 Roles & Jobs",
                value=f"**{player1}:** {get_role_emoji(p1_data.get('role', 'civilian'))} "
                      f"{p1_data.get('role', 'Civilian').title()} | "
                      f"{get_job_emoji(p1_data.get('job', 'unemployed'))} "
                      f"{p1_data.get('job', 'Unemployed').title()}\n"
                      f"**{player2}:** {get_role_emoji(p2_data.get('role', 'civilian'))} "
                      f"{p2_data.get('role', 'Civilian').title()} | "
                      f"{get_job_emoji(p2_data.get('job', 'unemployed'))} "
                      f"{p2_data.get('job', 'Unemployed').title()}",
                inline=False
            )
            
            # Winner determination
            if p1_playtime > p2_playtime:
                winner = f"🏆 **{player1}** leads by {format_playtime(p1_playtime - p2_playtime)}"
            elif p2_playtime > p1_playtime:
                winner = f"🏆 **{player2}** leads by {format_playtime(p2_playtime - p1_playtime)}"
            else:
                winner = "🤝 **Tied!** Both players have equal playtime"
            
            embed.add_field(
                name="🏅 Result",
                value=winner,
                inline=False
            )
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating player comparison: {e}")
            return None
    
    async def create_rotating_leaderboards(self) -> List[discord.Embed]:
        """Create multiple leaderboard embeds for rotation"""
        try:
            embeds = []
            
            # Main playtime leaderboard
            playtime_embed = await self.create_leaderboard_embed('playtime', 10)
            embeds.append(playtime_embed)
            
            # Recent players leaderboard
            recent_embed = await self.create_leaderboard_embed('recent', 10)
            embeds.append(recent_embed)
            
            return embeds
            
        except Exception as e:
            logger.error(f"Error creating rotating leaderboards: {e}")
            return []
    
    async def get_leaderboard_statistics(self) -> Dict[str, Any]:
        """Get overall leaderboard statistics"""
        try:
            total_players = await self.db.db.players.count_documents({})
            
            # Get top player
            top_players = await self.get_top_players(1)
            top_player = top_players[0] if top_players else None
            
            # Calculate total server playtime
            pipeline = [
                {"$group": {
                    "_id": None,
                    "total_playtime": {"$sum": "$playtime"},
                    "avg_playtime": {"$avg": "$playtime"}
                }}
            ]
            
            result = await self.db.db.players.aggregate(pipeline).to_list(1)
            stats = result[0] if result else {}
            
            return {
                'total_players': total_players,
                'top_player': top_player,
                'total_server_playtime': stats.get('total_playtime', 0),
                'average_playtime': stats.get('avg_playtime', 0),
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting leaderboard statistics: {e}")
            return {}
