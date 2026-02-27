KOSPEL_DIR=$HOME/kospel-snapshot
DATA_DIR=$HOME/export/radek
OUTFILE="kospel-$(date +'%Y%m').csv"

/root/kospel-snapshot/.venv/bin/python $KOSPEL_DIR/kospel.py -v --username $1 --password $2 --outfile $DATA_DIR/$OUTFILE >> $DATA_DIR/kospel.log
/root/kospel-snapshot/.venv/bin/python $KOSPEL_DIR/kospel.py -v --username $1 --password $2 --outfile $DATA_DIR/kospel.json
tail -50 $DATA_DIR/kospel.log > $DATA_DIR/kospel-tail.log
tail -300 $DATA_DIR/$OUTFILE > /tmp/.kosp1

