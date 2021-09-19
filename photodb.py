#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import logging
import os
import sys
import pathlib
import urllib.request
from datetime import datetime
from configparser import ConfigParser
from dataclasses import dataclass

import psycopg2
import exif

VERSION = "0.1.1"

dbdef = [
    "drop table if exists picture",
    """
create table picture (
    picture_id        serial primary key,
    blob_id           int,
    date_taken        timestamp with time zone,
    week_number       int,
    GPS_Latitude      double precision,
    GPS_Longitude     double precision,
    GPS_Altitude      double precision,
    Country           varchar(20),
    Region            varchar(20),
    City              varchar(30),
    pathname          varchar(128)
    )
""",
    "drop table if exists extra_data",
    """
create table extra_data (
    blob_id     serial primary key,
    picture_id  int,
    jsondata    bytea
    )
    """
]

@dataclass
class PictureRecord:
    date_taken: datetime = None
    week_number: int = 0
    GPS_Latitude: float = 0
    GPS_Longitude: float = 0
    GPS_Altitude: float = 0
    Country: str = ""
    Region: str = ""
    City: str = ""
    pathname: str = ""
    extra_data: dict = None
    picture_id: int = None
    blob_id: int = None

    def to_json(self):
        return {
            "date_taken": self.date_taken.isoformat(),
            "week": self.week_number,
            "latval": self.GPS_Latitude,
            "longval": self.GPS_Longitude,
            "alt": self.GPS_Altitude,
            "country": self.Country,
            "region": self.Region,
            "city": self.City,
            "pathname": self.pathname,
            #"picture_id": self.picture_id,
            #"blob_id": self.blob_id,
            "extra_data": self.extra_data,
            }

    @classmethod
    def from_json(cls, rec):
        instance = cls()
        instance.date_taken = datetime.fromisoformat(rec["date_taken"])
        instance.week_number = rec["week"]
        instance.GPS_Latitude = rec["latval"]
        instance.GPS_Longitude = rec["longval"]
        instance.GPS_Altitude = rec["alt"]
        instance.Country = rec["country"]
        instance.Region = rec["region"]
        instance.City = rec["city"]
        instance.pathname = rec["pathname"]
        instance.picture_id = rec.get("picture_id")
        instance.blob_id = rec.get("blob_id")
        instance.extra_data = rec.get("extra_data")
        return instance


OPENCAGE_ALLOWED_REQUESTS = 2500
class OpenCage:
    """
    Singleton patterned class
    Stores OpenCage API key and keeps track of remaining requests
    """
    instance = None

    def __new__(cls, key=None):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
            cls.instance.key = ""
            cls.instance.remaining = OPENCAGE_ALLOWED_REQUESTS
        if key is not None:
            cls.instance.key = key
        return cls.instance


DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_ERROR_LOG = "~/photodb_errors.log"
DEFAULT_CONFIG = "/usr/local/etc/photodb.ini"
SAVED_RECORDS = "~/.photodb_records"
stored_records = {}


class TooManyRequestsError(Exception):
    pass


class dummylog:
    def _print(self, st):
        print(st)

    error = warning = info = debug = _print


def setup_database(dbname, **kwargs):
    with psycopg2.connect(dbname=dbname, **kwargs) as cnx:
        with cnx.cursor() as cur:
            for statement in dbdef:
                cur.execute(statement)


def get_location_name(latitude, longitude, log):
    """Retrieve City, Region, Country from Geo Coordinates"""

    oc = OpenCage()
    if oc.remaining < 5: # 5 is a totally arbitrary limit
        raise TooManyRequestsError

    url = f"https://api.opencagedata.com/geocode/v1/json?q={latitude}+{longitude}&key={oc.key}"

    log.info(f"Retrieving inverse geolocation for: {latitude},{longitude}")
    rsp = urllib.request.urlopen(url)
    content = json.load(rsp)
    log.debug(json.dumps(content, indent=3))

    oc.remaining = int(content["rate"]["remaining"])

    if content["status"]["code"] != 200:
        log.error(f"{url} status: {content['status']}")
        return None, None, None, None

    results = content.get("results")
    if not results:
        log.error(f"{url} Empty results")
        return None, None, None, None
    components = results[0]["components"]
    city = components.get("city", components.get("town", ""))
    return city, components.get("state", ""), components["country"], content


def weeknumber(date_obj):
    return int(datetime.strftime(date_obj, "%W"))


def pic_get(pic, tag, default=None):
    """Get single tag ignoring exceptions"""
    try:
        return pic[tag]
    except Exception:
        return default


def get_picture_info(pic, log):
    # get the date, if no date set filedate
    dtstring = pic_get(pic, "datetime")
    if dtstring:
        log.debug(f"datetime field present: {dtstring}")
        date_taken = datetime.strptime(dtstring, "%Y:%m:%d %H:%M:%S")
    else:
        log.debug(f"datetime field NOT present.")
        date_taken = None

    # get the lat, long, alt if no gps set it to 0W 0N 0A
    latdegs, latmins, latsecs = pic_get(pic, "gps_latitude", (0, 0, 0))
    log.debug(f"GPS Latitude: {latdegs}, {latmins}, {latsecs}")
    latval = latdegs + latmins / 60.0 + latsecs / 3600.0
    latref = pic_get(pic, "gps_latitude_ref", "N")
    log.debug(f"GPS Latitude reference: {latref}")
    latval = -latval if latref == "S" else latval

    longdegs, longmins, longsecs = pic_get(pic, "gps_longitude", (0, 0, 0))
    log.debug(f"GPS Longitude: {longdegs}, {longmins}, {longsecs}")
    longval = longdegs + longmins / 60.0 + longsecs / 3600.0
    longref = pic_get(pic, "gps_longitude_ref", "W")
    log.debug(f"GPS Longitude reference: {longref}")
    longval = -longval if longref == "W" else longval

    city = region = country = ""
    extra_data = None
    if (0, 0) != (latval, longval) and abs(longval) <= 180.0:
        city, region, country, extra_data = get_location_name(latval, longval, log)

    alt = pic_get(pic, "gps_altitude", 0)
    log.debug(f"GPS Altitude: {alt}")
    altref = pic_get(pic, "gps_altitude_ref", exif.GpsAltitudeRef.ABOVE_SEA_LEVEL)
    log.debug(f"GPS Altitude reference: {altref}")
    alt = -alt if altref != exif.GpsAltitudeRef.ABOVE_SEA_LEVEL else alt

    return PictureRecord(date_taken,
                    weeknumber(date_taken) if date_taken else 0,
                    latval, longval, alt,
                    country, region, city,
                    "", # pathname
                    extra_data)


def record_exists(cnx, pathname):
    cur = cnx.cursor()
    cur.execute("select * from picture where pathname = %s limit 1", (str(pathname),))
    exists = len(list(cur.fetchall())) > 0
    cur.close()
    cnx.commit()
    return exists


def process_image_file(pathname, log):
    log.info(f"Processing picture from {pathname}")
    st = pathname.stat()
    filedate = datetime.fromtimestamp(st.st_mtime)

    with pathname.open("rb") as pf:
        pic = exif.Image(pf)

    picrec = get_picture_info(pic, log)

    if picrec.date_taken is None:
        picrec.date_taken = filedate
        picrec.week = weeknumber(picrec.date_taken)

    return picrec


def insert_record(cnx, picrec, log):
    cur = cnx.cursor()
    cur.execute(
        "insert into picture "
        "(date_taken, week_number, GPS_Latitude, "
        "GPS_Longitude, "
        "GPS_Altitude, "
        "Country, Region, City, pathname) values "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "returning picture_id",
        (
            picrec.date_taken,
            picrec.week_number,
            picrec.GPS_Latitude,
            picrec.GPS_Longitude,
            picrec.GPS_Altitude,
            picrec.Country[:20],
            picrec.Region[:20],
            picrec.City[:30],
            picrec.pathname
        ),
    )
    result = cur.fetchone()
    picrec.picture_id = picture_id = result[0]

    if picrec.extra_data:
        cur.execute(
            "insert into extra_data "
            "(picture_id, jsondata) values "
            "(%s, %s) returning blob_id",
            (picture_id, json.dumps(picrec.extra_data, indent=3).encode())
            )
        result = cur.fetchone()
        blob_id = result[0]
        cur.execute(
            "update picture set blob_id = %s where picture_id = %s",
            (blob_id, picture_id)
            )
        picrec.blob_id = blob_id
    cur.close()
    cnx.commit()
    return picrec


def insert_picture(cnx, pathname, root, log=None):
    global stored_records

    if root:
        sp = str(pathname.relative_to(root))
    else:
        sp = str(pathname)

    if record_exists(cnx, sp):
        log.info(f"Record pathname '{sp}' already in database")
        return

    picrec = process_image_file(pathname, log)
    picrec.pathname = sp

    picrec = insert_record(cnx, picrec, log)
    stored_records[sp] = picrec


def replay(cnx, recfile, log):
    with recfile.open() as fd:
        reclst = json.load(fd)

    for rec in reclst:
        if not record_exists(cnx, rec["pathname"]):
            log.info(f"Inserting record '{rec['pathname']}'")
            insert_record(cnx, PictureRecord.from_json(rec), log)
        else:
            log.info(f"Skipping record '{rec['pathname']}'")


def scan_directory(cnx, dirpath, log):
    for directory, dirs, files in os.walk(dirpath):
        for f in files:
            fpath = pathlib.Path(directory) / f
            if fpath.suffix.lower() in (".jpg", ".jpeg"):
                try:
                    insert_picture(cnx, fpath, dirpath, log)
                except TooManyRequestsError:
                    log.warning("Too many requests. Stopping.")
                    return
                except Exception as e:
                    cnx.rollback()
                    log.error(f"File {fpath} {e.__class__.__name__}: {e}",
                                exc_info=True)
                    continue

def extract_records(cnx, savedpth, log):
    lsrecs = []
    log.info(f"Dumping database to '{savedpth}'")

    with cnx.cursor() as cur:
        cur.execute("""
            select *
            from picture left join extra_data
                on picture.picture_id = extra_data.picture_id
        """)
        for rec in cur.fetchall():
            ed_fields = rec[11:]
            extra_data = None
            if any(ed_fields):
                extra_data = json.loads(bytes(ed_fields[2]).decode())
            pr = PictureRecord(
                    picture_id = rec[0],
                    blob_id = rec[1],
                    date_taken = rec[2],
                    week_number = rec[3],
                    GPS_Latitude = rec[4],
                    GPS_Longitude = rec[5],
                    GPS_Altitude = rec[6],
                    Country = rec[7],
                    Region = rec[8],
                    City = rec[9],
                    pathname = rec[10],
                    extra_data = extra_data
                    )
            lsrecs.append(pr)
        cnx.commit()
        save_records(savedpth, lsrecs, log)


def read_config(cfgfile):
    cp = ConfigParser()
    cp.read(cfgfile)
    return cp
    # return dict(cp["postgresdb"])


def read_saved_records(recfile, log):
    global stored_records
    try:
        with recfile.open() as fd:
            lst = json.load(fd)
    except FileNotFoundError:
        log.warning(f"File '{recfile}' not found.")
        return

    stored_records = {rec["pathname"]: PictureRecord.from_json(rec) for rec in lst}


def save_records(pthsave, reclist, log):
    with pthsave.open("w") as fd:
        fd.write("[\n")
        for i, pr in enumerate(reclist):
            if i > 0: # not the first value
                fd.write(",\n")
            fd.write(json.dumps(pr.to_json(), indent=3))
        fd.write("\n]\n")


def setup_logging(level, errlog):
    log = logging.getLogger(__name__)
    level = logging.getLevelName(level)
    log.setLevel(level)
    hdl = logging.StreamHandler()
    fmt = logging.Formatter(
        "%(asctime)s:%(levelname)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S"
    )
    hdl.setFormatter(fmt)
    log.addHandler(hdl)
    errhdl = logging.FileHandler(errlog)
    errhdl.setFormatter(fmt)
    errhdl.setLevel(logging.WARNING)
    log.addHandler(errhdl)
    return log


def get_cli_options(argv):
    p = argparse.ArgumentParser()
    p.add_argument(
        "--version",
        "-v",
        default=False,
        action="store_true",
        help="print version and exit",
    )
    p.add_argument(
        "--scan-dir",
        "-d",
        metavar="DIR",
        help="recursively scan a directory and add the "
             "pictures to the database",
    )
    p.add_argument(
        "--save",
        "-s",
        metavar="FILE",
        default=SAVED_RECORDS,
        help="save inserted records to FILE instead of default "
             f"{SAVED_RECORDS}",
    )
    p.add_argument(
        "--extract",
        "-x",
        metavar="FILE",
        help="extract all records from the database into a "
        "json FILE (opposite of --replay option)",
    )
    p.add_argument(
        "--replay",
        "-r",
        metavar="FILE",
        help="insert in the database the json records in FILE, previously "
        "specified with the --save option",
    )
    p.add_argument(
        "--picture",
        "-p",
        metavar="FILE",
        help="add a single picture file to the database",
    )
    p.add_argument(
        "--config",
        "-c",
        metavar="CFG-FILE",
        default=DEFAULT_CONFIG,
        help=f"read configuration from this file. Default: {DEFAULT_CONFIG}",
    )
    p.add_argument(
        "--initdb",
        "-i",
        default=False,
        action="store_true",
        help="initialise the database (specified in the configuration) "
             "WARNING: This wipes out an existing database!",
    )
    p.add_argument(
        "--loglevel",
        "-l",
        default=DEFAULT_LOG_LEVEL,
        help=f"set logging level. Default {DEFAULT_LOG_LEVEL}",
    )
    p.add_argument(
        "--errorlog",
        "-e",
        default=DEFAULT_ERROR_LOG,
        help=f"error log file. Default {DEFAULT_ERROR_LOG}. Errors will "
             "always get logged into a file. If you don't want that (bad "
             "idea) set this to /dev/null",
    )
    return p.parse_args(argv)


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    cliargs = get_cli_options(args)
    if cliargs.version:
        print(VERSION)
        return 0

    errlog = pathlib.Path(cliargs.errorlog).expanduser()
    log = setup_logging(cliargs.loglevel, errlog)
    cfg = pathlib.Path(cliargs.config)

    config = read_config(cfg)
    dbconfig = dict(config["postgresdb"])

        # Create OpenCage singleton object with the key
    OpenCage(config["opencage"]["apikey"])

    if cliargs.initdb:
        dbname = dbconfig.pop("dbname")
        log.info(f"Setting up database {dbname}")
        log.debug(f"Parameters: {json.dumps(dbconfig, indent=3)}")
        setup_database(dbname, **dbconfig)
        log.info(f"Database {dbname} ready.")
        return 0

    savedpth = pathlib.Path(cliargs.save).expanduser()
    read_saved_records(savedpth, log)

    with psycopg2.connect(**dbconfig) as cnx:
        if cliargs.picture:
            pic = pathlib.Path(cliargs.picture)
            insert_picture(cnx, pic, pic.parent, log)

        elif cliargs.scan_dir:
            scan_directory(cnx, pathlib.Path(cliargs.scan_dir), log)

        elif cliargs.replay:
            replay(cnx, pathlib.Path(cliargs.replay), log)

        elif cliargs.extract:
            extract_records(cnx, pathlib.Path(cliargs.extract), log)

    save_records(savedpth, stored_records.values(), log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
