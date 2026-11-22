# Preference and checkpoint storage checks

Run from the Unity project directory using a .NET SDK capable of building `net9.0`:

```powershell
dotnet run --project .\Tools\PreferencesCheck\PreferencesCheck.csproj --configuration Release -- .\Logs\Verification\preferences-check
```

These checks link the real `AppPreferencesStore.cs` and `LearningProgressStore.cs`,
with a small `JsonUtility` adapter for .NET. They verify migration, preference and
checkpoint separation, damaged files, backups, type validation and interrupted
saves against isolated folders. They do not launch Unity and do not replace the
Player tests of Unity's serializer and UI. Results are written to
`Logs/Verification/preferences-check/result.json`; no student profiles are used.
