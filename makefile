LDFLAGS = -lwiringPi

all: spispool

spispool:
	$(CC) $(CFLAGS) spispool.c -o spispool $(LDFLAGS)

clean:
	rm -f *.dSYM
	rm -f spispool

distclean:	clean
