KOSPEL_DIR=$HOME/kospel-snapshot
DATA_DIR=$HOME/export/radek
OUTFILE="kospel-$(date +'%Y%m').csv"

python3 $KOSPEL_DIR/kospel.py -v --username $1 --password $2 --outfile $DATA_DIR/$OUTFILE >> $DATA_DIR/kospel.log
python3 $KOSPEL_DIR/kospel.py -v --username $1 --password $2 --outfile $DATA_DIR/kospel.json
tail -50 $DATA_DIR/kospel.log > $DATA_DIR/kospel-tail.log
tail -300 $DATA_DIR/$OUTFILE > /tmp/.kosp1
# influx_push.py host org bucket token
python3 $KOSPEL_DIR/influx_push.py $3 $4 $5 $6 /tmp/.kosp1

