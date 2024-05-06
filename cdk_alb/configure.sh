#!/bin/bash
sudo yum update -y
sudo yum -y install git httpd php
sudo yum update -y git httpd php
sudo service httpd start
sudo chkconfig httpd on
sudo aws s3 cp s3://seis665-public/index.php /var/www/html/