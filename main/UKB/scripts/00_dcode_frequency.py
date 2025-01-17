'''
Compute raw disease frequencies across the UKB data
'''


## Modules
#=======================================================================================================================
import os 
import sys 
import shutil
import tqdm
import pickle
import dill
import h5py
import torch 
import pyro 

import probcox as pcox
import numpy as np 
import pandas as pd 

ROOT_DIR = '/nfs/research/sds/sds-ukb-cancer/'

sys.path.append(ROOT_DIR + 'projects/CancerRisk/scripts/model')
from m1 import predictor

  
#run_id = int(sys.argv[1]) # Variable from cluster
run_id=0
#run_id=100

print(run_id)

## Custom Functions
#=======================================================================================================================

def _mean(x):
    x = np.asarray(x)
    x = x[x != '']
    x = x.astype(float)
    if x.shape[0] != 0:
        return(np.mean(x).tolist())
    else:
        return('')
    
## Setup
#=======================================================================================================================
ukb_idx_remove = [1074413, 1220436, 1322418, 1373016, 1484804, 1516618, 1681957, 1898968, 2280037, 2326194, 2492542, 2672990, 2719152, 2753503, 3069616, 3100207, 3114030, 3622841, 3666774, 3683210, 4167470, 4285793, 4335116, 4426913, 4454074, 4463723, 4470984, 4735907, 4739147, 4940729, 5184071, 5938951]

disease_codes = np.load(ROOT_DIR + 'projects/CancerRisk/data/prep/disease_codes.npy', allow_pickle=True)
icd9_icd10_mapping = pd.read_csv(ROOT_DIR + 'projects/CancerRisk/data/raw/coding1836.tsv', sep='\t')
icd9_icd10_mapping.set_index('coding', drop=True, inplace=True)

icd10_codes = pd.read_csv(ROOT_DIR + 'projects/CancerRisk/data/raw/icd10_codes.csv', sep=',', header=None)
icd10_codes.loc[:, 1] = icd10_codes.loc[:, 1].apply(lambda x: x.split(' ')[4])
icd10_codes.set_index(0, drop=True, inplace=True)

events = ['oesophagus', 'stomach', 'colorectal', 'liver', 'pancreas', 'lung', 'melanoma', 'breast', 
                'cervix_uteri', 'corpus_uteri', 'ovary', 'prostate', 'testis', 'kidney', 'bladder', 'brain',
                'thyroid', 'non_hodgkin_lymphoma', 'multiple_myeloma', 'AML', 'other', 'death']

cancer_names = ['Oesophagus', 'Stomach', 'Colorectal', 'Liver', 'Pancreas', 'Lung', 'Melanoma', 'Breast', 
                'Cervix Uteri', 'Corpus Uteri', 'Ovary', 'Prostate', 'Testis', 'Kidney', 'Bladder', 'Brain',
                'Thyroid', 'Non-Hodgkin Lymphoma', 'Multiple Myeloma', 'AML']

cancer_codes = [['C15'], ['C16'], ['C18', 'C19', 'C20', 'C21'], ['C22'], ['C25'], ['C33', 'C34'], ['C43'],['C50'], ['C53'], ['C54'], ['C56'], ['C61'], ['C62'], ['C64'], ['C67'], ['C71'], ['C73'], ['C82', 'C83', 'C84', 'C85', 'C86'], ['C90'], ['C920', 'C924', 'C925', 'C926', 'C928', 'C930', 'C940', 'C942']]


# model 
tt = [pickle.load(open(ROOT_DIR + 'projects/CancerRisk/model/' + events[cc] + '/param.pkl', 'rb')) for cc in range(22)]


# summary table variables 
n = 0
nn=0
n_late_assessment = 0
n_age = 0 
prior_cancer = 0
prior_eoo = 0 
prior_ukb = 0


## Data Prep
#=======================================================================================================================
#ukb_iterator = pd.read_csv(ROOT_DIR + 'main/45632/ukb45632.csv', iterator=True, chunksize=1, nrows=5000, skiprows=lambda x: x in np.arange(1, 5000*run_id).tolist()) # iterate over ukb dataset for 5000 per job

#ukb_iterator_add = pd.read_csv(ROOT_DIR + 'main/44968/ukb44968s.csv', iterator=True, chunksize=1, nrows=5000, skiprows=lambda x: x in np.arange(1, 5000*run_id).tolist()) # iterate over ukb dataset for 5000 per job

#usecols=[0, 1445, 1446, 1447, 1448, 1449, 1450, 1451, 1452, 1453, 1454, 1455, 1456, 1457, 1458, 1459, 1460, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 806, 807, 808 ,809]

ukb_iterator = pd.read_csv(ROOT_DIR + 'main/45632/ukb45632.csv', iterator=True, chunksize=1, nrows=500000, skiprows=5000*run_id) # iterate over ukb dataset for 5000 per job

ukb_iterator_add = pd.read_csv(ROOT_DIR + 'main/44968/ukb44968s.csv', iterator=True, chunksize=1, nrows=500000, skiprows=5000*run_id) # iterate over ukb dataset for 5000 per job

dd_cols = np.asarray(pd.read_csv(ROOT_DIR + 'main/45632/ukb45632.csv', nrows=0).columns)
dd_add_cols = np.asarray(pd.read_csv(ROOT_DIR + 'main/44968/ukb44968s.csv', nrows=0).columns)

for _, [dd, dd_add] in tqdm.tqdm(enumerate(zip(ukb_iterator, ukb_iterator_add))):
    dd.columns = dd_cols
    dd_add.columns = dd_add_cols
    try:
        # check that the same ids are loaded
        assert dd.iloc[0, 0] == dd_add.iloc[0, 0]
        
        n += 1

        # basics - adj. transform everything to strings
        dd.reset_index(inplace=True)
        dd = dd.astype(str)
        dd = dd.replace('nan', '')

        dd_add.reset_index(inplace=True)
        dd_add = dd_add.astype(str)
        dd_add = dd_add.replace('nan', '')

        eid = np.asarray(dd['eid']).astype(int)
        if eid in ukb_idx_remove: # 
            prior_ukb += 1
            continue

        sex = np.asarray(dd['31-0.0']).astype(int) 
        birthyear = np.asarray(dd['34-0.0']).astype(str)[0]
        birthmonth = np.asarray(dd['52-0.0']).astype(str)[0]
        if len(birthmonth) == 1:
            birthmonth = '0' + birthmonth
        date_death = np.nanmin(np.asarray(dd[['40000-'+str(ii)+'.0' for ii in range(1)]]).astype('datetime64[D]'))
        EOO_reason = np.asarray(dd['190-0.0']).astype(str)
        EOO = np.asarray(dd['191-0.0']).astype('datetime64[D]')
        birthdate = np.datetime64(birthyear + '-' + birthmonth, 'D')[None]

        # remove if older than 75 yrs at 2015
        if np.logical_or((np.datetime64('2015-01-01') - birthdate).astype(float) < (50*365), (np.datetime64('2015-01-01') - birthdate).astype(float) > (75*365)): # 
            n_age += 1
            continue

        if EOO == EOO:
            pass
        else:
            EOO = np.datetime64('2018-04-10', 'D')[None] # set some end date of study
        EOO = np.minimum(EOO, np.datetime64('2018-04-10'))
        if date_death==date_death:
            EOO = np.minimum(EOO, date_death)

        # remove if dead or EOO before 2015
        if EOO <= np.datetime64('2015-01-01'):
            prior_eoo += 1
            continue

        assessment_dates = np.asarray(dd[['53-'+str(ii)+'.0' for ii in range(0,4)]])            
        idx = assessment_dates != ''
        assessment_dates = assessment_dates[idx]    
        assessment_dates = assessment_dates.astype('datetime64[D]')

        # remove if no assessment date before 2010
        if np.min(assessment_dates) > np.datetime64('2014-01-01'):
            n_late_assessment += 1
            continue
        visits = assessment_dates.shape[0]

        
        # extract first occurence data - cat 1712
        d_codes = []
        d_dates = []
        for ii in range(0, 3000, 2):
            try:
                a = np.asarray(dd_add[[str(130000 + ii) + '-0.0']])[0, 0]
                b = np.asarray(dd_add[[str(130000 + ii + 1) + '-0.0']])[0, 0]
                if np.logical_and(a != '', b != ''):
                    d_codes.extend(np.asarray(icd10_codes.loc[str(130000 + ii + 1) + '-0.0']).tolist())
                    d_dates.append(a)
            except:
                pass

        d_dates = np.asarray(d_dates).astype('datetime64[D]')   
        d_codes = np.asarray(d_codes).astype('str')  
        
        # HES records
        helpvar_a = np.asarray([dd['41270-0.'+str(ii)] for ii in range(213)])
        helpvar_b = np.asarray([dd['41280-0.'+str(ii)] for ii in range(213)])
        idx = helpvar_a != ''
        helpvar_a = helpvar_a[idx]
        for _ in range(helpvar_a.shape[0]):
            helpvar_a[_] = helpvar_a[_][:3]
        helpvar_b = helpvar_b[idx]
        helpvar_a = helpvar_a.astype('str')
        helpvar_b = helpvar_b.astype('datetime64[D]')   

        d_dates = np.concatenate((d_dates, helpvar_b))
        d_codes = np.concatenate((d_codes, helpvar_a))

        # sanity check
        idx = np.logical_and(d_dates>=birthdate, d_dates<=EOO) # should not change anyhting 
        d_dates = d_dates[idx]
        d_codes = d_codes[idx]   

        dates_cancer  = np.asarray(([])).astype('datetime64[D]')
        cancers = np.asarray(([])).astype('str')

        # death register
        death_primary = np.squeeze(dd[['40001-'+str(jj)+'.0' for jj in range(2)]])
        death_secondary = np.squeeze(dd[['40002-'+str(jj)+'.'+ str(kk) for jj in range(2) for kk in range(1, 15)]])
        death_cancer_idx = np.logical_or(np.any([ii[:1] == 'C' for ii in death_primary]), np.any([ii[:1] == 'C' for ii in death_secondary]))
        if death_cancer_idx:
            cancers = np.concatenate((cancers, death_primary[[ii[:1] == 'C' for ii in death_primary]], death_secondary[[ii[:1] == 'C' for ii in death_secondary]]))
            dates_cancer = np.concatenate((dates_cancer, np.repeat(date_death, cancers.shape[0])))

        # hospital register
        hes_cancer_idx = np.any([ii[:1] == 'C' for ii in d_codes])
        if hes_cancer_idx:
            dates_cancer = np.concatenate((dates_cancer, d_dates[[ii[:1] == 'C' for ii in d_codes]]))
            cancers = np.concatenate((cancers, d_codes[[ii[:1] == 'C' for ii in d_codes]]))

        # cancer registry
        dates_CR = np.asarray(dd[['40005-'+str(jj)+'.0' for jj in range(17)]])
        if np.sum(dates_CR!='')>0:
            CR_cancer = np.asarray(dd[['40006-'+str(jj)+'.0' for jj in range(17)]])
            CR_cancer_icd9 = np.asarray(dd[['40013-'+str(jj)+'.0' for jj in range(15)]])
            for _ in range(15):
                if CR_cancer_icd9[0, _] != '':
                    if CR_cancer[0, _] == '':
                        try:
                            CR_cancer[0, _] = np.asarray(icd9_icd10_mapping.loc[CR_cancer_icd9[0, _]])
                        except:
                            pass

            malignant_cancer = np.zeros((17,))
            for _ in range(17):
                if CR_cancer[0, _] != '':
                    if CR_cancer[0, _][0]=='C':
                        malignant_cancer[_] = 1

            helpvar = dates_CR!='' 
            dates_CR = dates_CR[helpvar]
            dates_CR = dates_CR.astype('datetime64[D]')
            CR_cancer = CR_cancer[helpvar]
            malignant_cancer = malignant_cancer[helpvar[0, :]]

            if np.sum(malignant_cancer)>0:
                dates_CR = dates_CR[malignant_cancer.astype(bool)]
                CR_cancer = CR_cancer[malignant_cancer.astype(bool)]
                dates_cancer = np.concatenate((dates_cancer,dates_CR))
                cancers = np.concatenate((cancers,CR_cancer))

        # Decision
        if dates_cancer.shape[0]>0:
            idxprimary = dates_cancer <= np.min(dates_cancer)+(31*3)
            dates_cancer = np.min(dates_cancer[idxprimary])
            EOO = np.minimum(EOO, dates_cancer)
            cancers = cancers[idxprimary]  
            if dates_cancer <= np.datetime64('2015-01-01'): 
                prior_cancer += 1
                continue

            if dates_cancer < np.datetime64('2018-04-10'):
                decision = np.asarray([np.logical_or(ii[:-1] in jj, ii in jj) for ii in cancers for jj in cancer_codes]).astype(int)

                if decision.shape[0] > 20:
                    decision=np.max(np.reshape(decision, (int(decision.shape[0]/20), 20)), axis=0)
                decision = np.concatenate((decision, np.zeros((2,))))
                if np.sum(decision) == 0:
                    decision[-2] = 1  
            else:
                decision = np.zeros((22,))
        else:
            dates_cancer = None
            cancer = None
            decision = np.zeros((22,))

        # Death
        if np.sum(decision) == 0:
            if date_death==date_death:
                if date_death < np.datetime64('2018-04-10'):
                    decision[-1] = 1  

        # remove disease after 2014
        idx = d_dates <= np.datetime64('2014-01-01')
        d_dates = d_dates[idx]
        d_codes = d_codes[idx]

        # matrix
        if d_codes.shape[0] > 0:
            d_time = -1*(d_dates - birthdate).astype(int)[:, None] - 1
            d_codes = (d_codes[:, None] == disease_codes[:, 0]).astype(float) # make matrix 
            
            d_codes = (np.min(d_codes*d_time, axis=0)*-1)[None, :]
        else:
            d_codes = np.zeros((1, 1305))
            
        with h5py.File(ROOT_DIR + 'projects/CancerRisk/data/main/disease_freq/ukb_' + str(run_id) + '.h5', 'a') as f:
            f.create_group(str(eid[0]))
            f[str(eid[0])].create_dataset('X', data=d_codes.astype(float), maxshape=(1, 1305), compression='lzf')
    except:
        print('ERROR')
        pass
#res = np.asarray([n, nn, n_late_assessment, n_age, prior_cancer, prior_eoo, prior_ukb])
#np.save(ROOT_DIR + 'projects/CancerRisk/data/main/table/res_' + str(run_id), res)


#for i in 0; do bsub -env "VAR1=$i" -n 1 -M 1000 -R "rusage[mem=1000]" './00_dcode_frequency.sh'; done
#for i in {1..100}; do bsub -env "VAR1=$i" -o /dev/null -e /dev/null -n 1 -M 1000 -R "rusage[mem=1000]" './00_dcode_frequency.sh'; done


