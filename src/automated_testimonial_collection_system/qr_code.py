import qrcode

url = "https://tally.so/r/BzyWAe?source=qr_code"
qr = qrcode.make(url)
qr.save("brew-and-bloom-testimonial.png")
