# Data live in versioned Icechunk stores: one GNSS store and one VOD store per site

Every write to a store is a commit in an Icechunk repository, so any
earlier state of the data can be read again, and a dataset can be cited
by its snapshot. A site has one GNSS store (all its receivers'
observations) and one VOD store (all its VOD analyses), not one store per
receiver or per day, so a network of sites is a short list of stores to
find and query.
