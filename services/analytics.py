import logging
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from services.database import DatabaseManager
from utils.helpers import format_playtime, calculate_percentage

logger = logging.getLogger(__name__)

class AnalyticsManager:
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.current_players = {}  
        self.session_start_times = {} 
        
        plt.switch_backend('Agg')
        plt.style.use('dark_background')
    
    async def update_player_data(self, players_data: List[Dict[str, Any]]):
        """Update player analytics data - FIXED VERSION"""
        try:
            current_time = datetime.utcnow()
            current_player_names = set()
            
            # Process current players
            for player in players_data:
                player_name = player.get('name')
                player_ping = player.get('ping', 0)
                
                if not player_name or player_name == 'Unknown':
                    continue
                
                current_player_names.add(player_name)
                
                # Calculate session time since last update (30 seconds)
                session_time_increment = 30  # seconds
                
                # If this is a new player joining
                if player_name not in self.current_players:
                    self.session_start_times[player_name] = current_time
                    session_time_increment = 0  # Don't add time for first detection
                    
                    # Log join event
                    await self.db.log_event('join', player_name, {
                        'ping': player_ping,
                        'identifiers': player.get('identifiers', [])
                    })
                    logger.info(f"Player joined: {player_name}")
                
                # Update current players tracking
                self.current_players[player_name] = {
                    'last_update': current_time,
                    'ping': player_ping,
                    'identifiers': player.get('identifiers', []),
                    'job': player.get('job', 'civilian'),
                    'role': player.get('role', 'civilian')
                }
                
                # Update database with incremental playtime
                await self.db.upsert_player({
                    'name': player_name,
                    'identifiers': player.get('identifiers', []),
                    'ping': player_ping,
                    'session_time': session_time_increment,
                    'job': player.get('job', 'civilian'),
                    'role': player.get('role', 'civilian')
                })
            
            # Handle players who left
            left_players = set(self.current_players.keys()) - current_player_names
            for player_name in left_players:
                # Calculate total session time
                if player_name in self.session_start_times:
                    session_duration = (current_time - self.session_start_times[player_name]).total_seconds()
                    
                    # Log leave event
                    await self.db.log_event('leave', player_name, {
                        'session_duration': session_duration
                    })
                    
                    # Update final session time
                    remaining_time = int(session_duration % 30)  # Any remaining time
                    if remaining_time > 0:
                        await self.db.upsert_player({
                            'name': player_name,
                            'session_time': remaining_time,
                            'identifiers': self.current_players[player_name].get('identifiers', []),
                            'ping': self.current_players[player_name].get('ping', 0),
                            'job': self.current_players[player_name].get('job', 'civilian'),
                            'role': self.current_players[player_name].get('role', 'civilian')
                        })
                    
                    logger.info(f"Player left: {player_name} (session: {format_playtime(int(session_duration))})")
                    
                    # Clean up tracking
                    del self.session_start_times[player_name]
                
                # Remove from current players
                del self.current_players[player_name]
        
        except Exception as e:
            logger.error(f"Error updating player data: {e}")
    
    async def log_ping_data(self, server_ping: float):
        """Log server ping data with player statistics"""
        try:
            player_pings = [
                data['ping'] for data in self.current_players.values() 
                if data['ping'] > 0
            ]
            
            if not player_pings:
                ping_stats = {
                    'low': server_ping,
                    'avg': server_ping,
                    'high': server_ping,
                    'server_ping': server_ping
                }
            else:
                ping_stats = {
                    'low': min(player_pings),
                    'avg': sum(player_pings) / len(player_pings),
                    'high': max(player_pings),
                    'server_ping': server_ping
                }
            
            await self.db.log_ping_data(ping_stats)
            
        except Exception as e:
            logger.error(f"Error logging ping data: {e}")
    
    async def get_player_info(self, player_name: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive player information"""
        try:
            player = await self.db.get_player(player_name)
            if not player:
                return None
            
            # Get recent events for this player
            recent_events = await self.db.get_recent_events(limit=50)
            player_events = [
                event for event in recent_events 
                if event.get('player_name') == player_name
            ]
            
            # Calculate additional stats
            join_events = [
                event for event in player_events 
                if event.get('event_type') == 'join'
            ]
            
            leave_events = [
                event for event in player_events 
                if event.get('event_type') == 'leave'
            ]
            
            total_sessions = len(join_events)
            
            # Calculate average session time from recent leave events
            recent_sessions = [
                event.get('details', {}).get('session_duration', 0)
                for event in leave_events[-10:]  # Last 10 sessions
                if event.get('details', {}).get('session_duration', 0) > 0
            ]
            
            avg_session = sum(recent_sessions) / len(recent_sessions) if recent_sessions else 0
            
            return {
                **player,
                'total_sessions': total_sessions,
                'recent_events': player_events[:5],  # Last 5 events
                'avg_ping': player.get('ping', 0),
                'avg_session_duration': int(avg_session),
                'is_online': player_name in self.current_players,
                'current_session_duration': self._get_current_session_duration(player_name)
            }
            
        except Exception as e:
            logger.error(f"Error getting player info for {player_name}: {e}")
            return None
    
    def _get_current_session_duration(self, player_name: str) -> int:
        """Get current session duration for online player"""
        if player_name in self.session_start_times:
            duration = (datetime.utcnow() - self.session_start_times[player_name]).total_seconds()
            return int(duration)
        return 0
    
    async def get_ping_stats(self, hours: int = 24) -> Optional[Dict[str, float]]:
        """Get ping statistics"""
        return await self.db.get_ping_stats(hours)
    
    async def get_server_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get comprehensive server statistics"""
        try:
            # Get basic analytics from database
            analytics = await self.db.get_server_analytics(days)
            
            # Get ping statistics
            ping_stats = await self.get_ping_stats(hours=days*24)
            
            # Get peak players from recent data
            peak_players = await self._calculate_peak_players(days)
            
            # Calculate uptime percentage
            uptime_percentage = await self._calculate_uptime_percentage(days)
            
            # Get active players count
            active_players = await self.db.get_active_players_count(hours=24)
            
            # Get current online count
            current_online = len(self.current_players)
            
            return {
                'peak_players': peak_players,
                'current_players': current_online,
                'avg_players': self._calculate_average_players(analytics),
                'avg_ping': ping_stats.get('avg', 0) if ping_stats else 0,
                'total_playtime': analytics.get('player_stats', {}).get('total_playtime', 0),
                'active_players': active_players,
                'uptime_percentage': uptime_percentage,
                'period_days': days,
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting server stats: {e}")
            return {}
    
    async def generate_stats_graph(self, days: int = 7) -> Optional[str]:
        """Generate server statistics graph"""
        try:
            # Get historical data
            stats_history = await self.db.get_stats_history(days)
            ping_data = await self._get_historical_ping_data(days)
            
            if not stats_history and not ping_data:
                logger.warning("No data available for graph generation")
                return None
            
            # Create figure with subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
            fig.patch.set_facecolor('#2f3136')
            
            # Plot 1: Player count over time
            if stats_history:
                dates = [stat['date'] for stat in stats_history]
                player_counts = [stat.get('peak_players', 0) for stat in stats_history]
                
                ax1.plot(dates, player_counts, color='#7289da', linewidth=2, marker='o')
                ax1.set_title('Peak Players (Last 7 Days)', color='white', fontsize=14)
                ax1.set_ylabel('Players', color='white')
                ax1.grid(True, alpha=0.3)
                ax1.tick_params(colors='white')
                
                # Format x-axis
                ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
                ax1.xaxis.set_major_locator(mdates.DayLocator())
            
            # Plot 2: Ping over time
            if ping_data:
                timestamps = [entry['timestamp'] for entry in ping_data]
                avg_pings = [entry['avg'] for entry in ping_data]
                low_pings = [entry['low'] for entry in ping_data]
                high_pings = [entry['high'] for entry in ping_data]
                
                ax2.plot(timestamps, avg_pings, color='#43b581', linewidth=2, label='Average')
                ax2.fill_between(timestamps, low_pings, high_pings, alpha=0.3, color='#43b581')
                ax2.set_title('Server Ping (Last 7 Days)', color='white', fontsize=14)
                ax2.set_ylabel('Ping (ms)', color='white')
                ax2.grid(True, alpha=0.3)
                ax2.tick_params(colors='white')
                ax2.legend()
                
                # Format x-axis
                ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
                ax2.xaxis.set_major_locator(mdates.DayLocator())
            
            # Style the plot
            for ax in [ax1, ax2]:
                ax.set_facecolor('#36393f')
                ax.spines['bottom'].set_color('white')
                ax.spines['top'].set_color('white')
                ax.spines['right'].set_color('white')
                ax.spines['left'].set_color('white')
            
            plt.tight_layout()
            
            # Save graph
            filename = f"server_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join('/tmp', filename)
            plt.savefig(filepath, facecolor='#2f3136', dpi=150, bbox_inches='tight')
            plt.close()
            
            return filepath
            
        except Exception as e:
            logger.error(f"Error generating stats graph: {e}")
            return None
    
    async def _calculate_peak_players(self, days: int) -> int:
        """Calculate peak players for specified period"""
        try:
            # Get historical peak from events
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            # Count concurrent players by analyzing join/leave events
            events = await self.db.get_recent_events(limit=1000)
            events = [e for e in events if e.get('timestamp', datetime.min) >= cutoff]
            
            if not events:
                return len(self.current_players)
            
            # Sort events by timestamp
            events.sort(key=lambda x: x.get('timestamp', datetime.min))
            
            # Track concurrent players over time
            concurrent_players = set()
            max_concurrent = 0
            
            for event in events:
                player_name = event.get('player_name')
                event_type = event.get('event_type')
                
                if event_type == 'join':
                    concurrent_players.add(player_name)
                elif event_type == 'leave':
                    concurrent_players.discard(player_name)
                
                max_concurrent = max(max_concurrent, len(concurrent_players))
            
            return max_concurrent
            
        except Exception as e:
            logger.error(f"Error calculating peak players: {e}")
            return len(self.current_players)
    
    def _calculate_average_players(self, analytics: Dict[str, Any]) -> float:
        """Calculate average players from analytics data"""
        try:
            player_stats = analytics.get('player_stats', {})
            total_players = player_stats.get('total_players', 0)
            
            # This is a simplified calculation
            # In a real implementation, you'd track hourly snapshots
            return float(total_players / 24) if total_players > 0 else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating average players: {e}")
            return 0.0
    
    async def _calculate_uptime_percentage(self, days: int) -> float:
        """Calculate server uptime percentage based on successful API calls"""
        try:
            # Get ping logs as a proxy for successful API calls
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            # Expected number of updates (every 30 seconds)
            expected_updates = (days * 24 * 60 * 60) / 30
            
            # Count actual ping logs
            actual_updates = await self.db.db.ping_logs.count_documents({
                "timestamp": {"$gte": cutoff}
            })
            
            if expected_updates == 0:
                return 100.0
            
            uptime = min((actual_updates / expected_updates) * 100, 100.0)
            return round(uptime, 1)
            
        except Exception as e:
            logger.error(f"Error calculating uptime: {e}")
            return 95.0  # Default reasonable uptime
    
    async def _get_historical_ping_data(self, days: int) -> List[Dict[str, Any]]:
        """Get historical ping data for graphing"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            # Get hourly ping averages
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff}}},
                {"$group": {
                    "_id": {
                        "year": {"$year": "$timestamp"},
                        "month": {"$month": "$timestamp"},
                        "day": {"$dayOfMonth": "$timestamp"},
                        "hour": {"$hour": "$timestamp"}
                    },
                    "avg": {"$avg": "$avg"},
                    "low": {"$min": "$low"},
                    "high": {"$max": "$high"}
                }},
                {"$sort": {"_id": 1}}
            ]
            
            results = await self.db.db.ping_logs.aggregate(pipeline).to_list(None)
            
            # Convert to proper format
            ping_data = []
            for result in results:
                timestamp = datetime(
                    result["_id"]["year"],
                    result["_id"]["month"],
                    result["_id"]["day"],
                    result["_id"]["hour"]
                )
                ping_data.append({
                    "timestamp": timestamp,
                    "avg": result["avg"],
                    "low": result["low"],
                    "high": result["high"]
                })
            
            return ping_data
            
        except Exception as e:
            logger.error(f"Error getting historical ping data: {e}")
            return []
    
    async def generate_player_trends(self) -> Dict[str, Any]:
        """Generate player trend analysis"""
        try:
            # Get player data for trend analysis
            current_week = await self.db.get_active_players_count(hours=24*7)
            previous_week_data = await self.db.get_active_players_count(hours=24*14)
            previous_week = max(0, previous_week_data - current_week)
            
            # Calculate trends
            if previous_week > 0:
                trend_percentage = ((current_week - previous_week) / previous_week) * 100
            else:
                trend_percentage = 100.0 if current_week > 0 else 0.0
            
            # Get top growing players (by playtime increase)
            top_players = await self.db.get_players_by_playtime(limit=5)
            
            return {
                'current_week_active': current_week,
                'previous_week_active': previous_week,
                'trend_percentage': round(trend_percentage, 1),
                'trend_direction': 'up' if trend_percentage > 0 else 'down' if trend_percentage < 0 else 'stable',
                'top_players': top_players,
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error generating player trends: {e}")
            return {}
    
    async def get_leaderboard_data(self, category: str = 'playtime', limit: int = 10) -> List[Dict[str, Any]]:
        """Get leaderboard data for different categories"""
        try:
            if category == 'playtime':
                return await self.db.get_players_by_playtime(limit)
            elif category == 'sessions':
                # Get players by session count
                pipeline = [
                    {"$group": {
                        "_id": "$player_name",
                        "sessions": {"$sum": {"$cond": [{"$eq": ["$event_type", "join"]}, 1, 0]}},
                        "last_seen": {"$max": "$timestamp"}
                    }},
                    {"$sort": {"sessions": -1}},
                    {"$limit": limit}
                ]
                
                results = await self.db.db.event_logs.aggregate(pipeline).to_list(limit)
                
                # Get full player data
                leaderboard = []
                for result in results:
                    player_data = await self.db.get_player(result["_id"])
                    if player_data:
                        player_data['total_sessions'] = result['sessions']
                        leaderboard.append(player_data)
                
                return leaderboard
            else:
                return await self.db.get_players_by_playtime(limit)
                
        except Exception as e:
            logger.error(f"Error getting leaderboard data: {e}")
            return []
    
    async def clean_offline_players(self):
        """Clean up offline players from current tracking"""
        try:
            current_time = datetime.utcnow()
            offline_threshold = timedelta(minutes=2)  # Players offline for 2+ minutes
            
            offline_players = []
            for player_name, data in list(self.current_players.items()):
                if current_time - data['last_update'] > offline_threshold:
                    offline_players.append(player_name)
            
            # Remove offline players and log leave events if not already logged
            for player_name in offline_players:
                if player_name in self.session_start_times:
                    session_duration = (current_time - self.session_start_times[player_name]).total_seconds()
                    
                    # Log leave event
                    await self.db.log_event('leave', player_name, {
                        'session_duration': session_duration,
                        'reason': 'timeout'
                    })
                    
                    logger.info(f"Player timed out: {player_name} (session: {format_playtime(int(session_duration))})")
                    del self.session_start_times[player_name]
                
                del self.current_players[player_name]
            
            if offline_players:
                logger.info(f"Cleaned {len(offline_players)} offline players from tracking")
            
        except Exception as e:
            logger.error(f"Error cleaning offline players: {e}")
    
    def get_current_online_count(self) -> int:
        """Get current online player count"""
        return len(self.current_players)
    
    def get_current_online_players(self) -> List[Dict[str, Any]]:
        """Get list of currently online players"""
        current_time = datetime.utcnow()
        return [
            {
                'name': name,
                'ping': data['ping'],
                'online_since': self.session_start_times.get(name, data['last_update']),
                'session_duration': int((current_time - self.session_start_times.get(name, data['last_update'])).total_seconds()),
                'job': data.get('job', 'civilian'),
                'role': data.get('role', 'civilian')
            }
            for name, data in self.current_players.items()
        ]
    
    async def force_player_update(self, player_name: str):
        """Force update a specific player's data"""
        try:
            if player_name in self.current_players:
                player_data = self.current_players[player_name]
                
                # Calculate current session time
                if player_name in self.session_start_times:
                    session_time = int((datetime.utcnow() - self.session_start_times[player_name]).total_seconds())
                else:
                    session_time = 0
                
                # Update database
                await self.db.upsert_player({
                    'name': player_name,
                    'identifiers': player_data.get('identifiers', []),
                    'ping': player_data.get('ping', 0),
                    'session_time': session_time,
                    'job': player_data.get('job', 'civilian'),
                    'role': player_data.get('role', 'civilian')
                })
                
                logger.info(f"Force updated player: {player_name}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error force updating player {player_name}: {e}")
            return False
    
    async def get_session_statistics(self) -> Dict[str, Any]:
        """Get current session statistics"""
        try:
            current_time = datetime.utcnow()
            online_players = self.get_current_online_players()
            
            if not online_players:
                return {
                    'total_online': 0,
                    'average_session_time': 0,
                    'longest_session': 0,
                    'average_ping': 0
                }
            
            session_times = [p['session_duration'] for p in online_players]
            pings = [p['ping'] for p in online_players if p['ping'] > 0]
            
            return {
                'total_online': len(online_players),
                'average_session_time': int(sum(session_times) / len(session_times)),
                'longest_session': max(session_times),
                'average_ping': round(sum(pings) / len(pings), 1) if pings else 0,
                'players': online_players
            }
            
        except Exception as e:
            logger.error(f"Error getting session statistics: {e}")
            return {
                'total_online': 0,
                'average_session_time': 0,
                'longest_session': 0,
                'average_ping': 0,
                'players': []
            }