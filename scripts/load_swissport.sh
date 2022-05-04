#!/bin/bash/
python deepfold/data/utils/load_swissport.py \
        --go-file data/go.obo \
        --swissprot-file  data/uniprot_sprot.dat.gz \
        --out-file data/data/swissprot.pkl
