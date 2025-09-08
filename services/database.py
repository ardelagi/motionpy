import motor.motor_asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from pymongo import IndexModel, ASCENDING, DESCENDING

logger = logging.getLogger(__name__)

class DatabaseManager:
    
    def __init__(self, mongodb_uri: str):
        self.mongodb_uri = mongodb_uri
        self.client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
        self.db: Optional[motor.motor_asyncio.AsyncIOMotorDatabase] = None
        
    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(self.mongodb_uri)
            
            # Get database name from URI or use default
            db_name = self.mongodb_uri.split('/')[-1] if '/' in self.mongodb_uri else 'motionlife_rp'
            self.db = self.client[db_name]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info("Connected to MongoDB successfully")
            
            # Initialize collections and indexes
            await self._setup_collections()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def _setup_collections(self):
        """Setup collections and indexes"""
        try:
            # Players collection indexes
            await self.db.players.create_indexes([
                IndexModel([("name", ASCENDING)], unique=True),
                IndexModel([("identifiers", ASCENDING)]),
                IndexModel([("lastSeen", DESCENDING)]),
                IndexModel([("playtime", DESCENDING)]),
                IndexModel([("firstSeen", ASCENDING)])
            ])
            
            # Ping logs collection indexes
            await self.db.ping_logs.create_indexes([
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("timestamp", ASCENDING)], expireAfterSeconds=2592000)  # 30 days TTL
            ])
            
            # Event logs collection indexes
            await self.db.event_logs.create_indexes([
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("event_type", ASCENDING)]),
                IndexModel([("player_name", ASCENDING)]),
                IndexModel([("player_name", ASCENDING), ("timestamp", DESCENDING)])
            ])
            
            # Server stats collection indexes
            await self.db.server_stats.create_indexes([
                IndexModel([("timestamp", DESCENDING)]),
                IndexModel([("date", ASCENDING)], unique=True)
            ])
            
            logger.info("Database collections and indexes setup completed")
            
        except Exception as e:
            logger.error(f"Error setting up collections: {e}")
    
    async def close(self):
        """Close database connection"""
        if self.client:
            self.client.close()
            logger.info("Database connection closed")
    
    # Player Management - FIXED VERSION
    async def upsert_player(self, player_data: Dict[str, Any]) -> bool:
        """Insert or update player data - FIXED TO HANDLE INCREMENTAL UPDATES"""
        try:
            filter_query = {"name": player_data["name"]}
            current_time = datetime.utcnow()
            
            # Check if player exists
            existing_player = await self.db.players.find_one(filter_query)
            
            update_data = {
                "$set": {
                    "name": player_data["name"],
                    "identifiers": player_data.get("identifiers", []),
                    "lastSeen": current_time,
                    "job": player_data.get("job", "civilian"),
                    "role": player_data.get("role", "civilian"),
                    "ping": player_data.get("ping", 0)
                },
                "$inc": {
                    "playtime": player_data.get("session_time", 0)
                }
            }
            
            # Set initial data for new players
            if not existing_player:
                update_data["$setOnInsert"] = {
                    "firstSeen": current_time,
                    "totalSessions": 0
                }
                logger.info(f"Creating new player record: {player_data['name']}")
            
            result = await self.db.players.update_one(
                filter_query, 
                update_data, 
                upsert=True
            )
            
            if result.acknowledged and player_data.get("session_time", 0) > 0:
                logger.debug(f"Updated player {player_data['name']} playtime by {player_data.get('session_time', 0)} seconds")
            
            return result.acknowledged
            
        except Exception as e:
            logger.error(f"Error upserting player {player_data.get('name', 'Unknown')}: {e}")
            return False
    
    async def get_player(self, name: str) -> Optional[Dict[str, Any]]:
        """Get player data by name"""
        try:
            player = await self.db.players.find_one({"name": name})
            if player:
                # Ensure required fields exist
                player.setdefault('playtime', 0)
                player.setdefault('totalSessions', 0)
                player.setdefault('job', 'civilian')
                player.setdefault('role', 'civilian')
                player.setdefault('ping', 0)
            return player
            
        except Exception as e:
            logger.error(f"Error getting player {name}: {e}")
            return None
    
    async def get_players_by_playtime(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top players by playtime"""
        try:
            cursor = self.db.players.find({
                "playtime": {"$gt": 0}  # Only players with actual playtime
            }).sort("playtime", DESCENDING).limit(limit)
            
            players = await cursor.to_list(length=limit)
            
            # Ensure all required fields
            for player in players:
                player.setdefault('playtime', 0)
                player.setdefault('totalSessions', 0)
                player.setdefault('job', 'civilian')
                player.setdefault('role', 'civilian')
                player.setdefault('name', 'Unknown')
            
            return players
            
        except Exception as e:
            logger.error(f"Error getting players by playtime: {e}")
            return []
    
    async def get_active_players_count(self, hours: int = 24) -> int:
        """Get count of active players in last N hours"""
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            count = await self.db.players.count_documents({
                "lastSeen": {"$gte": cutoff}
            })
            return count
            
        except Exception as e:
            logger.error(f"Error getting active players count: {e}")
            return 0
    
    async def increment_player_sessions(self, player_name: str) -> bool:
        """Increment player session count"""
        try:
            result = await self.db.players.update_one(
                {"name": player_name},
                {"$inc": {"totalSessions": 1}}
            )
            return result.acknowledged
            
        except Exception as e:
            logger.error(f"Error incrementing sessions for {player_name}: {e}")
            return False
    
    # Ping Logging
    async def log_ping_data(self, ping_data: Dict[str, Any]) -> bool:
        """Log server ping data"""
        try:
            log_entry = {
                "timestamp": datetime.utcnow(),
                "low": float(ping_data.get("low", 0)),
                "avg": float(ping_data.get("avg", 0)),
                "high": float(ping_data.get("high", 0)),
                "server_ping": float(ping_data.get("server_ping", 0))
            }
            
            result = await self.db.ping_logs.insert_one(log_entry)
            return result.acknowledged
            
        except Exception as e:
            logger.error(f"Error logging ping data: {e}")
            return False
    
    async def get_ping_stats(self, hours: int = 24) -> Optional[Dict[str, float]]:
        """Get ping statistics for last N hours"""
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff}}},
                {"$group": {
                    "_id": None,
                    "avg_low": {"$avg": "$low"},
                    "avg_ping": {"$avg": "$avg"},
                    "avg_high": {"$avg": "$high"},
                    "min_ping": {"$min": "$low"},
                    "max_ping": {"$max": "$high"},
                    "count": {"$sum": 1}
                }}
            ]
            
            result = await self.db.ping_logs.aggregate(pipeline).to_list(1)
            if result and result[0]["count"] > 0:
                stats = result[0]
                return {
                    "low": round(stats.get("avg_low", 0), 1),
                    "avg": round(stats.get("avg_ping", 0), 1),
                    "high": round(stats.get("avg_high", 0), 1),
                    "min": round(stats.get("min_ping", 0), 1),
                    "max": round(stats.get("max_ping", 0), 1)
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting ping stats: {e}")
            return None
    
    # Event Logging - ENHANCED VERSION
    async def log_event(self, event_type: str, player_name: str, details: Dict[str, Any] = None) -> bool:
        """Log player events (join/leave) with enhanced data"""
        try:
            event_entry = {
                "timestamp": datetime.utcnow(),
                "event_type": event_type,
                "player_name": player_name,
                "details": details or {}
            }
            
            result = await self.db.event_logs.insert_one(event_entry)
            
            # If it's a join event, increment session count
            if event_type == "join" and result.acknowledged:
                await self.increment_player_sessions(player_name)
            
            return result.acknowledged
            
        except Exception as e:
            logger.error(f"Error logging event {event_type} for {player_name}: {e}")
            return False
    
    async def get_recent_events(self, limit: int = 50, event_type: str = None) -> List[Dict[str, Any]]:
        """Get recent player events with optional filtering"""
        try:
            filter_query = {}
            if event_type:
                filter_query["event_type"] = event_type
            
            cursor = self.db.event_logs.find(filter_query).sort("timestamp", DESCENDING).limit(limit)
            events = await cursor.to_list(length=limit)
            
            return events
            
        except Exception as e:
            logger.error(f"Error getting recent events: {e}")
            return []
    
    async def get_player_events(self, player_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get events for specific player"""
        try:
            cursor = self.db.event_logs.find({
                "player_name": player_name
            }).sort("timestamp", DESCENDING).limit(limit)
            
            events = await cursor.to_list(length=limit)
            return events
            
        except Exception as e:
            logger.error(f"Error getting events for player {player_name}: {e}")
            return []
    
    # Server Statistics
    async def save_daily_stats(self, stats_data: Dict[str, Any]) -> bool:
        """Save daily server statistics"""
        try:
            today = datetime.utcnow()
            today_start = datetime(today.year, today.month, today.day)
            
            filter_query = {"date": today_start}
            update_data = {
                "$set": {
                    "date": today_start,
                    "timestamp": datetime.utcnow(),
                    **stats_data
                }
            }
            
            result = await self.db.server_stats.update_one(
                filter_query,
                update_data,
                upsert=True
            )
            
            return result.acknowledged
            
        except Exception as e:
            logger.error(f"Error saving daily stats: {e}")
            return False
    
    async def get_stats_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get server statistics history"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            cutoff_start = datetime(cutoff.year, cutoff.month, cutoff.day)
            
            cursor = self.db.server_stats.find({
                "date": {"$gte": cutoff_start}
            }).sort("date", ASCENDING)
            
            stats = await cursor.to_list(length=days)
            return stats
            
        except Exception as e:
            logger.error(f"Error getting stats history: {e}")
            return []
    
    # Analytics Queries
    async def get_server_analytics(self, days: int = 7) -> Dict[str, Any]:
        """Get comprehensive server analytics"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            # Get player statistics
            player_pipeline = [
                {"$match": {"lastSeen": {"$gte": cutoff}}},
                {"$group": {
                    "_id": None,
                    "total_players": {"$sum": 1},
                    "total_playtime": {"$sum": "$playtime"},
                    "avg_playtime": {"$avg": "$playtime"},
                    "max_playtime": {"$max": "$playtime"}
                }}
            ]
            
            player_stats = await self.db.players.aggregate(player_pipeline).to_list(1)
            
            # Get ping statistics
            ping_stats = await self.get_ping_stats(hours=days*24)
            
            # Get event statistics
            event_pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff}}},
                {"$group": {
                    "_id": "$event_type",
                    "count": {"$sum": 1}
                }}
            ]
            
            event_stats = await self.db.event_logs.aggregate(event_pipeline).to_list(10)
            
            return {
                "player_stats": player_stats[0] if player_stats else {
                    "total_players": 0,
                    "total_playtime": 0,
                    "avg_playtime": 0,
                    "max_playtime": 0
                },
                "ping_stats": ping_stats or {},
                "event_stats": {stat["_id"]: stat["count"] for stat in event_stats},
                "period_days": days,
                "generated_at": datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting server analytics: {e}")
            return {}
    
    async def get_player_count_over_time(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get player count changes over time"""
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            # Get join/leave events grouped by hour
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff}}},
                {"$group": {
                    "_id": {
                        "year": {"$year": "$timestamp"},
                        "month": {"$month": "$timestamp"},
                        "day": {"$dayOfMonth": "$timestamp"},
                        "hour": {"$hour": "$timestamp"},
                        "event_type": "$event_type"
                    },
                    "count": {"$sum": 1}
                }},
                {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1, "_id.hour": 1}}
            ]
            
            results = await self.db.event_logs.aggregate(pipeline).to_list(None)
            
            # Process results into hourly data
            hourly_data = {}
            for result in results:
                hour_key = f"{result['_id']['year']}-{result['_id']['month']:02d}-{result['_id']['day']:02d}-{result['_id']['hour']:02d}"
                if hour_key not in hourly_data:
                    hourly_data[hour_key] = {"joins": 0, "leaves": 0}
                
                if result['_id']['event_type'] == 'join':
                    hourly_data[hour_key]['joins'] = result['count']
                elif result['_id']['event_type'] == 'leave':
                    hourly_data[hour_key]['leaves'] = result['count']
            
            return [
                {
                    "hour": hour,
                    "joins": data["joins"],
                    "leaves": data["leaves"],
                    "net_change": data["joins"] - data["leaves"]
                }
                for hour, data in hourly_data.items()
            ]
            
        except Exception as e:
            logger.error(f"Error getting player count over time: {e}")
            return []
    
    async def cleanup_old_data(self):
        """Clean up old data based on retention policies"""
        try:
            # Clean up old ping logs (older than 30 days)
            ping_cutoff = datetime.utcnow() - timedelta(days=30)
            ping_result = await self.db.ping_logs.delete_many({
                "timestamp": {"$lt": ping_cutoff}
            })
            
            # Clean up old event logs (older than 90 days)
            event_cutoff = datetime.utcnow() - timedelta(days=90)
            event_result = await self.db.event_logs.delete_many({
                "timestamp": {"$lt": event_cutoff}
            })
            
            # Update players who haven't been seen in 30 days (mark as inactive)
            inactive_cutoff = datetime.utcnow() - timedelta(days=30)
            inactive_result = await self.db.players.update_many(
                {"lastSeen": {"$lt": inactive_cutoff}},
                {"$set": {"status": "inactive"}}
            )
            
            logger.info(
                f"Cleanup completed: {ping_result.deleted_count} ping logs, "
                f"{event_result.deleted_count} events deleted, "
                f"{inactive_result.modified_count} players marked inactive"
            )
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    # Health Check
    async def health_check(self) -> Dict[str, Any]:
        """Perform database health check"""
        try:
            # Test basic operations
            await self.client.admin.command('ping')
            
            # Get collection counts
            players_count = await self.db.players.count_documents({})
            ping_logs_count = await self.db.ping_logs.count_documents({})
            events_count = await self.db.event_logs.count_documents({})
            
            # Get recent activity
            recent_events = await self.db.event_logs.count_documents({
                "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=1)}
            })
            
            # Check for recent player activity
            active_players = await self.db.players.count_documents({
                "lastSeen": {"$gte": datetime.utcnow() - timedelta(hours=24)}
            })
            
            return {
                "status": "healthy",
                "collections": {
                    "players": players_count,
                    "ping_logs": ping_logs_count,
                    "event_logs": events_count
                },
                "recent_activity": {
                    "events_last_hour": recent_events,
                    "active_players_24h": active_players
                },
                "timestamp": datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow()
            }
    
    async def get_player_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for players by name (partial match)"""
        try:
            # Use regex for partial matching
            cursor = self.db.players.find({
                "name": {"$regex": query, "$options": "i"}
            }).sort("playtime", DESCENDING).limit(limit)
            
            players = await cursor.to_list(length=limit)
            return players
            
        except Exception as e:
            logger.error(f"Error searching for players with query '{query}': {e}")
            return []