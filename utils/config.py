import os
from typing import Optional

class Config:
    """Configuration manager for environment variables"""
    
    def __init__(self):
        # Discord Configuration
        self.DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
        self.GUILD_ID = int(os.getenv('GUILD_ID', 0)) or None
        
        # MongoDB Configuration
        self.MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/motionlife_rp')
        
        # FiveM Configuration
        self.FIVEM_BASE_URL = os.getenv('FIVEM_BASE_URL', 'http://localhost:3007')
        
        # Redis Configuration
        self.REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
        
        # Channel IDs
        self.LEADERBOARD_CHANNEL_ID = int(os.getenv('LEADERBOARD_CHANNEL_ID', 0)) or None
        self.NOTIFICATIONS_CHANNEL_ID = int(os.getenv('NOTIFICATIONS_CHANNEL_ID', 0)) or None
        self.ADMIN_CHANNEL_ID = int(os.getenv('ADMIN_CHANNEL_ID', 0)) or None
        
        # Bot Settings
        self.UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 30))
        self.PRESENCE_ROTATION_INTERVAL = int(os.getenv('PRESENCE_ROTATION_INTERVAL', 10))
        self.LEADERBOARD_UPDATE_INTERVAL = int(os.getenv('LEADERBOARD_UPDATE_INTERVAL', 300))
        
        # Analytics Settings
        self.PING_LOG_RETENTION_DAYS = int(os.getenv('PING_LOG_RETENTION_DAYS', 30))
        self.PLAYER_DATA_RETENTION_DAYS = int(os.getenv('PLAYER_DATA_RETENTION_DAYS', 90))
        
        # Validate required settings
        self._validate_config()
    
    def _validate_config(self):
        """Validate required configuration values"""
        if not self.DISCORD_TOKEN:
            raise ValueError("DISCORD_TOKEN is required")
        
        if not self.MONGODB_URI:
            raise ValueError("MONGODB_URI is required")
        
        if not self.FIVEM_BASE_URL:
            raise ValueError("FIVEM_BASE_URL is required")
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return os.getenv('ENVIRONMENT', 'development').lower() == 'production'
    
    def get_database_name(self) -> str:
        """Get database name from MongoDB URI"""
        try:
            return self.MONGODB_URI.split('/')[-1]
        except:
            return 'motionlife_rp'
