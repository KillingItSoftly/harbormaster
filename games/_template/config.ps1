@{
    GameName        = '<DisplayName>'        # PascalCase, e.g. 'Windrose'
    EnvVarPrefix    = '<ENV_PREFIX>'         # uppercase, e.g. 'WINDROSE'

    # Steam
    SteamAppId      = '<SteamAppId>'
    InstallDir      = 'C:\GameServers\<DisplayName>'
    SteamCmdPath    = 'C:\SteamCMD\steamcmd.exe'

    # Service (NSSM)
    ServiceName     = '<DisplayName>Server'
    ServerExePath   = 'C:\GameServers\<DisplayName>\<DisplayName>Server.exe'

    # Save paths
    SavedDataPath   = 'C:\GameServers\<DisplayName>\Saved'
    LogPath         = 'C:\GameServers\<DisplayName>\logs\server-stdout.log'

    # Backups
    LocalBackupRoot = 'C:\Backups\<DisplayName>'
    StorageAccount  = '<fill-in>'
    BlobContainer   = '<fill-in>'
    LocalRetention  = 14
    BlobRetention   = 30

    # Game-specific log patterns (defaults match Unreal Engine output)
    CrashLogPattern   = 'Crash Stack Trace'
    LogTimestampRegex = '\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}):\d+\]'
}
