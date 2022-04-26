# TDF2MZML
## Python script to convert Bruker TDF format to MzML

### Tested with TimsTof Pro TDF 2.0 using SDK version 2.8.7
#### support added for DIA data. DIA MS/MS only supports centroid output

### SDK Requirement
The preffered method to run this application is via docker. Bruker has allowed us to include the lib and python api (SDK version 2.8.7) in this repo for the purpose of building the docker image. To run the python script outside of docker you will need to obtain the SDK directly from Bruker.

### USAGE
```bash
usage: tdf2mzml.py [-h] -i input_file -o output_file 
            [-s value] [-e value]
            [--ms1_type value] [--compression value]

optional arguments:
  -h, --help show this help message and exit
  -i input_file, --input input_file
  -o output_file, --output output_file
  -s value, --start_frame value
  -e value, --end_frame value
  --ms1_type value "raw:profile:centroid"
  --compression value "zlib:none"
```

## DOCKER USAGE
A Dockerfile is also provided to assist with building and running the utility inside a docker container.  The docker image is also hosted on docker_hub

### To use docker to convert a tdf file. 

```
docker run --rm -it -v $PWD:/data mfreitas/tdf2mzml tdf2mzml.py -i /data/your_folder.d 
```
This command will create a new MzML file in the same folder as the tdf directory.

### To build a docker image. 
```
docker build -t tdf2mzml .
```

### To run the docker image

```
docker run --rm -it -v $PWD:/data tdf2mzml tdf2mzml.py -i /data/your_folder.d 
```

