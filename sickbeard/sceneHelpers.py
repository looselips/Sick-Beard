# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.

from sickbeard import common
from sickbeard import logger
from sickbeard import db

import re
import datetime

from name_parser.parser import NameParser, InvalidNameException

resultFilters = ("sub(pack|s|bed)", "nlsub(bed|s)?", "swesub(bed)?",
                 "(dir|sample|nfo)fix", "sample", "(dvd)?extras", 
                 "dubbed", "german", "french", "core2hd")

def filterBadReleases(name):

    try:
        fp = NameParser()
        parse_result = fp.parse(name)
    except InvalidNameException:
        logger.log(u"Unable to parse the filename "+name+" into a valid episode", logger.WARNING)
        return False

    # if there's no info after the season info then assume it's fine
    if not parse_result.extra_info:
        return True

    # if any of the bad strings are in the name then say no
    for x in resultFilters:
        if re.search('(^|[\W_])'+x+'($|[\W_])', parse_result.extra_info, re.I):
            logger.log(u"Invalid scene release: "+name+" contains "+x+", ignoring it", logger.DEBUG)
            return False

    return True

def sanitizeSceneName (name):
    for x in ",:()'!":
        name = name.replace(x, "")

    name = name.replace("- ", ".").replace(" ", ".").replace("&", "and").replace('/','.')
    name = re.sub("\.\.*", ".", name)

    if name.endswith('.'):
        name = name[:-1]

    return name

def sceneToNormalShowNames(name):

    if not name:
        return []

    name_list = [name]
    
    # use both and and &
    new_name = re.sub('(?i)([\. ])and([\. ])', '\\1&\\2', name, re.I)
    if new_name not in name_list:
        name_list.append(new_name)

    results = []

    for cur_name in name_list:
        # add brackets around the year
        results.append(re.sub('(\D)(\d{4})$', '\\1(\\2)', cur_name))
    
        # add brackets around the country
        country_match_str = '|'.join(common.countryList.values())
        results.append(re.sub('(?i)([. _-])('+country_match_str+')$', '\\1(\\2)', cur_name))

    results += name_list

    return list(set(results))

def makeSceneShowSearchStrings(show):

    showNames = allPossibleShowNames(show)

    # scenify the names
    return map(sanitizeSceneName, showNames)


def makeSceneSeasonSearchString (show, segment, extraSearchType=None):

    myDB = db.DBConnection()

    if show.is_air_by_date:
        numseasons = 0
        
        # the search string for air by date shows is just 
        seasonStrings = [segment]
    
    else:
        numseasonsSQlResult = myDB.select("SELECT COUNT(DISTINCT season) as numseasons FROM tv_episodes WHERE showid = ? and season != 0", [show.tvdbid])
        numseasons = int(numseasonsSQlResult[0][0])

        seasonStrings = ["S%02d" % segment]
        # since nzbmatrix allows more than one search per request we search SxEE results too
        if extraSearchType == "nzbmatrix":
            seasonStrings.append("%ix" % segment)

    showNames = set(makeSceneShowSearchStrings(show))

    toReturn = []
    term_list = []

    # search each show name
    for curShow in showNames:
        # most providers all work the same way
        if not extraSearchType:
            # if there's only one season then we can just use the show name straight up
            if numseasons == 1:
                toReturn.append(curShow)
            # for providers that don't allow multiple searches in one request we only search for Sxx style stuff
            else:
                for cur_season in seasonStrings:
                    toReturn.append(curShow + "." + cur_season)
        
        # nzbmatrix is special, we build a search string just for them
        elif extraSearchType == "nzbmatrix":
            if numseasons == 1:
                toReturn.append('"'+curShow+'"')
            elif numseasons == 0:
                toReturn.append('"'+curShow+' '+str(segment).replace('-',' ')+'"')
            else:
                term_list = [x+'*' for x in seasonStrings]
                if show.is_air_by_date:
                    term_list = ['"'+x+'"' for x in term_list]

                toReturn.append('"'+curShow+'"')
    
    if extraSearchType == "nzbmatrix":     
        toReturn = ['+('+','.join(toReturn)+')']
        if term_list:
            toReturn.append('+('+','.join(term_list)+')')
    return toReturn


def makeSceneSearchString (episode):

    myDB = db.DBConnection()
    numseasonsSQlResult = myDB.select("SELECT COUNT(DISTINCT season) as numseasons FROM tv_episodes WHERE showid = ? and season != 0", [episode.show.tvdbid])
    numseasons = int(numseasonsSQlResult[0][0])

    # see if we should use dates instead of episodes
    if episode.show.is_air_by_date and episode.airdate != datetime.date.fromordinal(1):
        epStrings = [str(episode.airdate)]
    else:
        epStrings = ["S%02iE%02i" % (int(episode.season), int(episode.episode)),
                    "%ix%02i" % (int(episode.season), int(episode.episode))]

    # for single-season shows just search for the show name
    if numseasons == 1:
        epStrings = ['']

    showNames = set(makeSceneShowSearchStrings(episode.show))

    toReturn = []

    for curShow in showNames:
        for curEpString in epStrings:
            toReturn.append(curShow + '.' + curEpString)

    return toReturn

def allPossibleShowNames(show):

    showNames = [show.name]

    if int(show.tvdbid) in common.sceneExceptions:
        showNames += common.sceneExceptions[int(show.tvdbid)]

    # if we have a tvrage name then use it
    if show.tvrname != "" and show.tvrname != None:
        showNames.append(show.tvrname)

    newShowNames = []

    country_list = common.countryList
    country_list.update(dict(zip(common.countryList.values(), common.countryList.keys())))

    # if we have "Show Name Australia" or "Show Name (Australia)" this will add "Show Name (AU)" for
    # any countries defined in common.countryList
    # (and vice versa)
    for curName in set(showNames):
        for curCountry in country_list:
            if curName.endswith(' '+curCountry):
                newShowNames.append(curName.replace(' '+curCountry, ' ('+country_list[curCountry]+')'))
            elif curName.endswith(' ('+curCountry+')'):
                newShowNames.append(curName.replace(' ('+curCountry+')', ' ('+country_list[curCountry]+')'))

    showNames += newShowNames

    return showNames

def isGoodResult(name, show, log=True):
    """
    Use an automatically-created regex to make sure the result actually is the show it claims to be
    """

    all_show_names = allPossibleShowNames(show)
    showNames = map(sanitizeSceneName, all_show_names) + all_show_names

    for curName in set(showNames):
        escaped_name = re.sub('\\\\[.-]', '\W+', re.escape(curName))
        curRegex = '^' + escaped_name + '\W+(?:(?:S\d\d)|(?:\d\d?x)|(?:\d{4}\W\d\d\W\d\d)|(?:(?:part|pt)[\._ -]?(\d|[ivx]))|Season\W+\d+\W+|E\d+\W+)'
        if log:
            logger.log(u"Checking if show "+name+" matches " + curRegex, logger.DEBUG)

        match = re.search(curRegex, name, re.I)

        if match:
            return True

    if log:
        logger.log(u"Provider gave result "+name+" but that doesn't seem like a valid result for "+show.name+" so I'm ignoring it")
    return False
