import datetime
import logging
import os
import pathlib
import subprocess

import numpy as np
import pandas as pd

import urllib, json


_log = logging.getLogger('covid19_inference.data_retrieval')


def clone_jhu_at_time(checkout_time:datetime.datetime, workdir:os.PathLike):
    """Obtain history JHU dataset by git cloning at a time point in the past.

    Parameters
    ----------
    checkout_time : datetime.datetime
        A timezone-aware datetime object, representing a time point in the past
    workdir : os.PathLike
        a directory to which the data may be cloned. For example a tempfile.TemporaryDirectory
        
    Returns
    -------
    fp_confirmed : os.PathLike
        path to time_series_covid19_confirmed_global.csv
    fp_deaths : os.PathLike
        path to time_series_covid19_deaths_global.csv
    fp_recovered : os.PathLike
        path to time_series_covid19_recovered_global.csv 
    """
    if not checkout_time.tzinfo:
        raise ValueError('The [checkout_time] must be timezone-aware!')
    # clone
    repodir = pathlib.Path(workdir, 'jhu_repo')
    repo = 'https://github.com/CSSEGISandData/COVID-19'
    _log.info(f'Cloning "{repo}" to "{repodir}"')
    subprocess.run(f'git clone {repo} {repodir}')

    # find the commit hash that was relevant at the selected date
    checkout_time = checkout_time.isoformat()
    _log.info(f'Finding the last commit before {checkout_time}')
    commit_id = subprocess.run(
        f'git rev-list -1 --until="{checkout_time}" master',
        cwd=repodir, stdout=subprocess.PIPE, encoding='utf8'
    ).stdout.strip()
    if len(commit_id) != 40:
        raise Exception(f'Failed to find a valid commit id before the specified checkout_time ({checkout_time})')
    
    _log.info(f'Checking out commit {commit_id}')
    subprocess.run(
        f'git checkout {commit_id}',
        cwd=repodir, stdout=subprocess.PIPE, encoding='utf8',
        # this step is important - we must not fail silently
        check=True
    )

    dp_ts = pathlib.Path(repodir, 'csse_covid_19_data', 'csse_covid_19_time_series')
    fp_confirmed = pathlib.Path(dp_ts, 'time_series_covid19_confirmed_global.csv')
    fp_deaths = pathlib.Path(dp_ts, 'time_series_covid19_deaths_global.csv')
    fp_recovered = pathlib.Path(dp_ts, 'time_series_covid19_recovered_global.csv')
    return fp_confirmed, fp_deaths, fp_recovered


def _jhu_to_iso(fp_csv:str) -> pd.DataFrame:
    """Convert Johns Hopkins University dataset to nicely formatted DataFrame.

    Drops Lat/Long columns and reformats to a multi-index of (country, state).

    Parameters
    ----------
    fp_csv : string

    Returns
    -------
    : pandas.DataFrame
    """
    df = pd.read_csv(fp_csv, sep=',')
    # change columns & index
    df = df.drop(columns=['Lat', 'Long']).rename(columns={
        'Province/State': 'state',
        'Country/Region': 'country'
    })
    df = df.set_index(['country', 'state'])
    # datetime columns
    df.columns = [datetime.datetime.strptime(d, '%m/%d/%y') for d in df.columns]
    return df


def get_jhu_cdr(
        country:str, state:str,
        fp_confirmed:str='https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv',
        fp_deaths:str='https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_deaths_global.csv',
        fp_recovered:str='https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_recovered_global.csv',
    ) -> pd.DataFrame:
    """Gets confirmed, deaths and recovered Johns Hopkins University dataset as a DataFrame with datetime index.

    Parameters
    ----------
    country : string
        name of the country (the "Country/Region" column), can be None if state is set
    state : string
        name of the state (the "Province/State" column), can be None if country is set
    fp_confirmed : string
        filepath or URL pointing to the original CSV of global confirmed cases
    fp_deaths : string
        filepath or URL pointing to the original CSV of global deaths
    fp_recovered : string
        filepath or URL pointing to the original CSV of global recovered cases

    Returns
    -------
    : pandas.DataFrame
    """
    # load & transform
    df_confirmed = _jhu_to_iso(fp_confirmed)
    df_deaths = _jhu_to_iso(fp_deaths)
    df_recovered = _jhu_to_iso(fp_recovered)

    # filter
    df = pd.DataFrame(columns=['date', 'confirmed', 'deaths', 'recovered']).set_index('date')
    df['confirmed'] = df_confirmed.loc[(country, state)]
    df['deaths'] = df_deaths.loc[(country, state)]
    df['recovered'] = df_recovered.loc[(country, state)]
    df.index.name = 'date'

    return df


def get_jhu_confirmed_cases():
    """
        Attempts to download the most current data from the online repository of the
        Coronavirus Visual Dashboard operated by the Johns Hopkins University
        and falls back to the backup provided with our repo if it fails.
        Only works if the module is located in the repo directory.

        Returns
        -------
        : confirmed_cases
            pandas table with confirmed cases
    """
    try:
        url = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv"
        confirmed_cases = pd.read_csv(url, sep=",")
    except Exception as e:
        print("Failed to download current data, using local copy.")
        this_dir = os.path.dirname(__file__)
        confirmed_cases = pd.read_csv(
            this_dir + "/../data/confirmed_global_fallback_2020-04-07.csv", sep=","
        )

    return confirmed_cases


def get_jhu_deaths():
    """
        Attempts to download the most current data from the online repository of the
        Coronavirus Visual Dashboard operated by the Johns Hopkins University
        and falls back to the backup provided with our repo if it fails.
        Only works if the module is located in the repo directory.

        Returns
        -------
        : deaths
            pandas table with reported deaths
    """
    try:
        url = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_deaths_global.csv"
        deaths = pd.read_csv(url, sep=",")
    except Exception as e:
        print("Failed to download current data, using local copy.")
        this_dir = os.path.dirname(__file__)
        deaths = pd.read_csv(
            this_dir + "/../data/confirmed_global_fallback_2020-04-07.csv", sep=","
        )

    return deaths


def filter_one_country(data_df, country, begin_date, end_date):
    """
    Returns the number of cases of one country as a np.array, given a dataframe returned by `get_jhu_confirmed_cases`
    Parameters
    ----------
    data_df : pandas.dataframe
    country : string
    begin_date : datetime.datetime
    end_date: datetime.datetime

    Returns
    -------
    : array
    """
    date_formatted_begin = _format_date(begin_date)
    date_formatted_end = _format_date(end_date)

    y = data_df[(data_df['Province/State'].isnull()) & (data_df['Country/Region']==country)]

    if len(y)==1:
        cases_obs = y.loc[:,date_formatted_begin:date_formatted_end]
    elif len(y)==0:
        cases_obs = data_df[data_df['Country/Region']==country].sum().loc[date_formatted_begin:date_formatted_end]

    else:
        raise RuntimeError('Country not found: {}'.format(country))

    return np.array(cases_obs).flatten()


def get_last_date(data_df):
    last_date = data_df.columns[-1]
    month, day, year = map(int, last_date.split("/"))
    return datetime.datetime(year + 2000, month, day)


def get_rki():

    '''
    Downloads Robert Koch Institute data, separated by region (landkreis)
    
    Returns
    -------
    dataframe
        dataframe containing all the RKI data from arcgis.
    '''

    #Gets all unique landkreis_id from data
    url_id = 'https://services7.arcgis.com/mOBPykOjAyBO2ZKk/ArcGIS/rest/services/RKI_COVID19/FeatureServer/0/query?where=0%3D0&objectIds=&time=&resultType=none&outFields=idLandkreis&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly=false&returnDistinctValues=true&cacheHint=false&orderByFields=&groupByFieldsForStatistics=&outStatistics=&having=&resultOffset=&resultRecordCount=&sqlFormat=none&f=pjson&token='
    url = urllib.request.urlopen(url_id)
    json_data = json.loads(url.read().decode())
    n_data = len(json_data['features'])
    unique_ids = [json_data['features'][i]['attributes']['IdLandkreis'] for i in range(n_data)]

    #If the number of landkreise differs from 412, uses local copy (query system can behave weirdly during updates)
    if n_data == 412:

        print('Downloading {:d} unique Landkreise'.format(n_data))

        df_keys = ['Bundesland', 'Landkreis', 'Altersgruppe', 'Geschlecht', 'AnzahlFall',
           'AnzahlTodesfall', 'Meldedatum', 'NeuerFall']

        df = pd.DataFrame(columns=df_keys)

        #Fills DF with data from all landkreise
        for idlandkreis in unique_ids:
            url_str = 'https://services7.arcgis.com/mOBPykOjAyBO2ZKk/ArcGIS/rest/services/RKI_COVID19/FeatureServer/0/query?where=IdLandkreis%3D%27'+ idlandkreis + '%27&objectIds=&time=&resultType=none&outFields=Bundesland%2C+Landkreis%2C+Altersgruppe%2C+Geschlecht%2C+AnzahlFall%2C+AnzahlTodesfall%2C+Meldedatum%2C+NeuerFall&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly=false&returnDistinctValues=false&cacheHint=false&orderByFields=&groupByFieldsForStatistics=&outStatistics=&having=&resultOffset=&resultRecordCount=&sqlFormat=none&f=pjson&token='
            
            with urllib.request.urlopen(url_str) as url:
                json_data = json.loads(url.read().decode())

            n_data = len(json_data['features'])

            if n_data > 5000:
                ValueError('Query limit exceeded')

            data_flat = [json_data['features'][i]['attributes'] for i in range(n_data)]

            df_temp = pd.DataFrame(data_flat)
        
            #Very inneficient, but it will do
            df = pd.concat([df, df_temp], ignore_index=True)

        df['date'] = df['Meldedatum'].apply(lambda x: datetime.datetime.fromtimestamp(x/1e3))   

    else:

        print("Failed to download current data, using local copy.")
        this_dir = os.path.dirname(__file__)
        df = pd.read_csv(this_dir + "/../data/rki_fallback.csv", sep=",")
        df['date'] = pd.to_datetime(df['date'], format='%d-%m-%Y')

    return df

def filter_rki(df, begin_date, end_date, variable = 'AnzahlFall', level = None, value = None):
    """Filters the RKI dataframe.
    
    Parameters
    ----------
    df : dataframe
        dataframe obtained from get_rki()
    begin_date : DateTime
        initial date to return
    end_date : DateTime
        last date to return
    variable : str, optional
        type of variable to return: cases ("AnzahlFall"), deaths ("AnzahlTodesfall")
    level : None, optional
        whether to return data from all Germany (None), a state ("Bundesland") or a region ("Landkreis")
    value : None, optional
        string of the state/region
    
    Returns
    -------
    np.array
        array with the requested variable, in the requested range.
    """

    #Input parsing
    if variable not in ['AnzahlFall', 'AnzahlTodesfall', 'Total']:
        ValueError('Invalid variable. Valid options: "AnzahlFall", "AnzahlTodesfall", "Total"')

    if level not in ['Landkreis', 'Bundesland', None]:
        ValueError('Invalid level. Valid options: "Landkreis", "Bundesland", None')

    if variable == 'Total':
        df['Total'] = df['NeuerFall'] + df['AnzahlFall']    

    #Keeps only the relevant data
    if level is not None:
        df = df[df[level]==value][['date', value]]

    df_series = df.groupby('date')[variable].sum().cumsum()

    return np.array(df_series[begin_date:end_date])


_format_date = lambda date_py: "{}/{}/{}".format(
    date_py.month, date_py.day, str(date_py.year)[2:4]
)
