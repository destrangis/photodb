=======
Photodb
=======

Index a collection of photographs into a PostgreSQL database.

In order to scratch an itch of mine, I decided to index my digital photograph
collection by creating a database with the file pathname, the date the
picture it was taken, and the place, obtained from the GPS coordinates.
Some of my pictures were sent to me via social networks, which
regrettably strip all the metadata from the files and, in this case,
only the date the picture was obtained (i.e. the file creation date) is
stored. In the future who knows, tags and people's names may be added.

Dependencies
------------

This program depends on the modules `psycopg2 <https://pypi.org/project/psycopg2/>`_,
to manage the PostgreSQL database, and `exif <https://pypi.org/project/exif/>`_
to extract metadata from digital photograph files.

The programs does reverse geolocation using a public API from
`OpenCage <https://opencagedata.com>`_. You will need to obtain an API
key from them in order to run this program.

Running
-------

There is no automated install or setup.py program at this time, so the
recommended way to use this program for now is:

Create a database on a postgreSQL server to store the data into.

Create a virtual environment and install the dependencies in the
directory on which you have git cloned this repo::

    $ python3 -m venv photodb
    $ cd photodb
    $ . bin/activate
    (photodb)$ python3 -m pip install -r < requirements.txt

Copy the file ``photodb.ini.sample`` into ``config.ini`` and edit it with
the details of your OpenCage API key and your database.

Initialise the database::

    (photodb)$ python3 photodb.py --config=config.ini --initdb

And at this point you can index your picture collection into the database
by running the program::

    (photodb)$ python3 photodb.py --config=config.ini --scan-dir=/path/to/pics

You can get help on the different options the program can take by using
the --help command line option::

    (photodb)$ python3 photodb.py --help
    usage: photodb.py [-h] [--version] [--scan-dir DIR] [--save FILE]
                      [--extract FILE] [--replay FILE] [--picture FILE]
                      [--config CFG-FILE] [--initdb] [--loglevel LOGLEVEL]
                      [--errorlog ERRORLOG]

    optional arguments:
      -h, --help            show this help message and exit
      --version, -v         print version and exit
      --scan-dir DIR, -d DIR
                            recursively scan a directory and add the pictures to
                            the database
      --save FILE, -s FILE  save inserted records to FILE instead of default
                            ~/.photodb_records
      --extract FILE, -x FILE
                            extract all records from the database into a json FILE
                            (opposite of --replay option)
      --replay FILE, -r FILE
                            insert in the database the json records in FILE,
                            previously specified with the --save option
      --picture FILE, -p FILE
                            add a single picture file to the database
      --config CFG-FILE, -c CFG-FILE
                            read configuration from this file. Default:
                            /usr/local/etc/photodb.ini
      --initdb, -i          initialise the database (specified in the
                            configuration) WARNING: This wipes out an existing
                            database!
      --loglevel LOGLEVEL, -l LOGLEVEL
                            set logging level. Default INFO
      --errorlog ERRORLOG, -e ERRORLOG
                            error log file. Default ~/photodb_errors.log. Errors
                            will always get logged into a file. If you don't want
                            that (bad idea) set this to /dev/null

The program is a bit (too much?) paranoid about not repeating calls to
the OpenCage site, and saves a json copy of the records inserted as a
backup, which can eventually be really big. It can, at a later time,
rebuild the database without re-scanning the files and without querying
OpenCage. That would be the purpose of the ``--save``, ``--extract``,
and ``--replay`` command line options.

Configuration
-------------

The configuration is taken by default from the file ``/usr/local/photodb.ini``.
If you don't have the configuration file there, or you want to use a
different configuration file, you can always use the ``--config`` command
line option.

A sample configuration file is provided in ``config.ini.sample`` which
contains the following::

    # these are the parameters for your postgresql database
    [postgresdb]
    dbname=testphotodb
    user=testuser
    password=hello
    host=localhost
    port=5432

    # this stores your OpenCage API key for doing inverse geolocation
    [opencage]
    apikey = b1ab1ab1ab1ab1ab1ab1ab1ab1ab1ab1

License
-------
This program is released under the **MIT License**
