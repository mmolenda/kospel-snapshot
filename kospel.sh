KOSPEL_DIR=$HOME/kospel-snapshot
OUTFILE="kospel-$(date +'%Y%m').csv"

python3 $KOSPEL_DIR/kospel.py -v --username $1 --password $2 --outfile $KOSPEL_DIR/$OUTFILE >> $KOSPEL_DIR/kospel.log
tail -50 $KOSPEL_DIR/kospel.log > $KOSPEL_DIR/kospel-tail.log
tail -300 $KOSPEL_DIR/$OUTFILE > /tmp/.kosp1
python3 $KOSPEL_DIR/influx_push.py /tmp/.kosp1
rclone copy $KOSPEL_DIR/$OUTFILE gdrive:Kospel/
rclone copy $KOSPEL_DIR/kospel-tail.log gdrive:Kospel/
