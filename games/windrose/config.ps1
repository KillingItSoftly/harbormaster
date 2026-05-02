@{
    GameName        = 'Windrose'
    EnvVarPrefix    = 'WINDROSE'

    # Steam
    SteamAppId      = '4129620'
    InstallDir      = 'C:\GameServers\Windrose'
    SteamCmdPath    = 'C:\SteamCMD\steamcmd.exe'

    # Service
    ServiceName     = 'WindroseServer'
    ServerExePath   = 'C:\GameServers\Windrose\WindroseServer.exe'

    # Save paths
    SavedDataPath   = 'C:\GameServers\Windrose\R5\Saved'
    LogPath         = 'C:\GameServers\Windrose\logs\server-stdout.log'

    # Backups
    LocalBackupRoot = 'C:\Backups\Windrose'
    StorageAccount  = 'backupserversaves'
    BlobContainer   = 'windrosebackups'
    LocalRetention  = 14
    BlobRetention   = 30

    # Game-specific patterns
    CrashLogPattern = 'Crash Stack Trace'
    LogTimestampRegex = '\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}):\d+\]'
}