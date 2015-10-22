# coding=utf-8
import string
import os
import urllib
import zipfile
import re
import copy
import subliminal
import subliminal_patch
import subzero
import logger

from datetime import timedelta
from subzero.recent_items import getRecentItems
from subzero.background import DefaultScheduler

from subzero.subtitlehelpers import getSubtitlesFromMetadata
from subzero.config import config

OS_PLEX_USERAGENT = 'plexapp.com v9.0'

DEPENDENCY_MODULE_NAMES = ['subliminal', 'subliminal_patch', 'enzyme', 'guessit', 'requests']
PERSONAL_MEDIA_IDENTIFIER = "com.plexapp.agents.none"

def Start():
    HTTP.CacheTime = 0
    HTTP.Headers['User-agent'] = OS_PLEX_USERAGENT
    Log.Debug("START CALLED")
    logger.registerLoggingHander(DEPENDENCY_MODULE_NAMES)
    # configured cache to be in memory as per https://github.com/Diaoul/subliminal/issues/303
    subliminal.region.configure('dogpile.cache.memory')

    # init defaults; perhaps not the best idea to use ValidatePrefs here, but we'll see
    ValidatePrefs()

    #recent_items = getRecentItems()
    #print recent_items
    scheduler = DefaultScheduler()
    scheduler.run()
    scheduler.stop()

def ValidatePrefs():
    Log.Debug("Validate Prefs called.")
    config.initialize()
    return 

def initSubliminalPatches():
    # configure custom subtitle destination folders for scanning pre-existing subs
    dest_folder = config.subtitleDestinationFolder
    subliminal_patch.patch_video.CUSTOM_PATHS = [dest_folder] if dest_folder else []
    subliminal_patch.patch_provider_pool.DOWNLOAD_TRIES = int(Prefs['subtitles.try_downloads'])
    subliminal_patch.patch_providers.addic7ed.USE_BOOST = bool(Prefs['provider.addic7ed.boost'])

def scanTvMedia(media):
    videos = {}
    for season in media.seasons:
        for episode in media.seasons[season].episodes:
            for item in media.seasons[season].episodes[episode].items:
                for part in item.parts:
                    scannedVideo = scanVideo(part, "episode")
                    videos[scannedVideo] = part
    return videos

def scanMovieMedia(media):
    videos = {}
    for item in media.items:
        for part in item.parts:
            scannedVideo = scanVideo(part, "movie")
            videos[scannedVideo] = part 
    return videos

def scanVideo(part, video_type):
    embedded_subtitles = Prefs['subtitles.scan.embedded']
    external_subtitles = Prefs['subtitles.scan.external']

    Log.Debug("Scanning video: %s, subtitles=%s, embedded_subtitles=%s" % (part.file, external_subtitles, embedded_subtitles))
    try:
        return subliminal.video.scan_video(part.file, subtitles=external_subtitles, embedded_subtitles=embedded_subtitles, video_type=video_type)
    except ValueError:
        Log.Warn("File could not be guessed by subliminal")

def downloadBestSubtitles(video_part_map, min_score=0):
    hearing_impaired = Prefs['subtitles.search.hearingImpaired']
    languages = config.langList
    if not languages: 
	return

    missing_languages = False
    for video, part in video_part_map.iteritems():
	if not Prefs['subtitles.save.filesystem']:
	    # scan for existing metadata subtitles
	    meta_subs = getSubtitlesFromMetadata(part)
	    for language, subList in meta_subs.iteritems():
		if subList:
		    video.subtitle_languages.add(language)
		    Log.Debug("Found metadata subtitle %s for %s", language, video)

	if not (languages - video.subtitle_languages):
    	    Log.Debug('All languages %r exist for %s', languages, video)
	    continue
	missing_languages = True
	break

    if missing_languages:
	Log.Debug("Download best subtitles using settings: min_score: %s, hearing_impaired: %s" %(min_score, hearing_impaired))
    
	return subliminal.api.download_best_subtitles(video_part_map.keys(), languages, min_score, hearing_impaired, providers=config.providers, provider_configs=config.providerSettings)
    Log.Debug("All languages for all requested videos exist. Doing nothing.")

def saveSubtitles(videos, subtitles):
    if Prefs['subtitles.save.filesystem']:
        Log.Debug("Using filesystem as subtitle storage")
        saveSubtitlesToFile(subtitles)
    else:
        Log.Debug("Using metadata as subtitle storage")
        saveSubtitlesToMetadata(videos, subtitles)

def saveSubtitlesToFile(subtitles):
    fld_custom = Prefs["subtitles.save.subFolder.Custom"].strip() if bool(Prefs["subtitles.save.subFolder.Custom"]) else None
    
    for video, video_subtitles in subtitles.items():
	if not video_subtitles:
	    continue

	fld = None
	if fld_custom or Prefs["subtitles.save.subFolder"] != "current folder":
    	    # specific subFolder requested, create it if it doesn't exist
            fld_base = os.path.split(video.name)[0]
            if fld_custom:
                if fld_custom.startswith("/"):
                    # absolute folder
                    fld = fld_custom
                else:
                    fld = os.path.join(fld_base, fld_custom)
            else:
                fld = os.path.join(fld_base, Prefs["subtitles.save.subFolder"])
            if not os.path.exists(fld):
                os.makedirs(fld)
        subliminal.api.save_subtitles(video, video_subtitles, directory=fld)

def saveSubtitlesToMetadata(videos, subtitles):
    for video, video_subtitles in subtitles.items():
        mediaPart = videos[video]
        for subtitle in video_subtitles: 
            mediaPart.subtitles[Locale.Language.Match(subtitle.language.alpha2)][subtitle.page_link] = Proxy.Media(subtitle.content, ext="srt")

def updateLocalMedia(media, media_type="movies"):
    # Look for subtitles
    if media_type == "movies":
	for item in media.items:
    	    for part in item.parts:
		subzero.localmedia.findSubtitles(part)
	return

    # Look for subtitles for each episode.
    for s in media.seasons:
      # If we've got a date based season, ignore it for now, otherwise it'll collide with S/E folders/XML and PMS
      # prefers date-based (why?)
      if int(s) < 1900 or metadata.guid.startswith(PERSONAL_MEDIA_IDENTIFIER):
        for e in media.seasons[s].episodes:
          for i in media.seasons[s].episodes[e].items:

            # Look for subtitles.
            for part in i.parts:
              subzero.localmedia.findSubtitles(part)
      else:
        pass

class SubZeroSubtitlesAgentMovies(Agent.Movies):
    name = 'Sub-Zero Subtitles (Movies)'
    languages = [Locale.Language.English]
    primary_provider = False
    contributes_to = ['com.plexapp.agents.imdb', 'com.plexapp.agents.xbmcnfo', 'com.plexapp.agents.themoviedb']

    def search(self, results, media, lang):
        Log.Debug("MOVIE SEARCH CALLED")
        results.Append(MetadataSearchResult(id='null', score=100))

    def update(self, metadata, media, lang):
        Log.Debug("MOVIE UPDATE CALLED")
	initSubliminalPatches()
        videos = scanMovieMedia(media)
        subtitles = downloadBestSubtitles(videos, min_score=int(Prefs["subtitles.search.minimumMovieScore"]))
	if subtitles:
    	    saveSubtitles(videos, subtitles)
	
	updateLocalMedia(media, media_type="movies")

class SubZeroSubtitlesAgentTvShows(Agent.TV_Shows):
    
    name = 'Sub-Zero Subtitles (TV)'
    languages = [Locale.Language.English]
    primary_provider = False
    contributes_to = ['com.plexapp.agents.thetvdb', 'com.plexapp.agents.thetvdbdvdorder', 'com.plexapp.agents.xbmcnfotv']

    def search(self, results, media, lang):
        Log.Debug("TV SEARCH CALLED")
        results.Append(MetadataSearchResult(id='null', score=100))

    def update(self, metadata, media, lang):
        Log.Debug("TvUpdate. Lang %s" % lang)
	initSubliminalPatches()
        videos = scanTvMedia(media)
        subtitles = downloadBestSubtitles(videos, min_score=int(Prefs["subtitles.search.minimumTVScore"]))
	if subtitles:
    	    saveSubtitles(videos, subtitles)

	updateLocalMedia(media, media_type="series")

