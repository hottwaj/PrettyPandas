from __future__ import unicode_literals

try:
    from pandas.core.style import Styler
except ImportError:
    from pandas.io.formats.style import Styler

from pandas.api.types import is_float
import pandas as pd
import numpy as np

from collections import namedtuple, defaultdict
from itertools import product
from functools import partial
from numbers import Number
import warnings

from .formatters import PERCENT_FORMATTERS, as_money, as_unit, as_currency, LOCALE_OBJ


def apply_pretty_globals():
    """Apply global CSS to make dataframes pretty.

    This function injects HTML and CSS code into the notebook in order to make
    tables look pretty. Third party hosts of notebooks advise against using
    this and some don't support it. As long as you are okay with HTML injection
    in your notebook, go ahead and use this. Otherwise use the ``PrettyPandas``
    class.
    """
    from IPython.display import HTML
    return HTML("""
        <style type='text/css'>
            /* Pretty Pandas Dataframes */
            .dataframe * {border-color: #c0c0c0 !important;}
            .dataframe th{background: #eee;}
            .dataframe td{
                background: #fff;
                text-align: right;
                min-width:5em;
            }

            /* Format summary rows */
            .dataframe-summary-row tr:last-child,
            .dataframe-summary-col td:last-child{
                background: #eee;
                font-weight: 500;
            }
        </style>
        """)


Formatter = namedtuple("Formatter", "subset, exclude, axis, function")

class PrettyPandas(Styler):
    """Pretty pandas dataframe Styles.

    Parameters
    ----------
    :param data: Series or DataFrame
    :param precision: int
        precision to round floats to, defaults to pd.options.display.precision
    :param table_styles: list-like, default None
        list of {selector: (attr, value)} dicts. These values overwrite the
        default style.
    :param uuid: str, default None
        a unique identifier to avoid CSS collisons; generated automatically
    :param caption: str, default None
        caption to attach to the table
    :param summary_rows:
        list of single-row dataframes to be appended as a summary
    :param summary_cols:
        list of single-row dataframes to be appended as a summary
    """

    #: Default colour for header backgrounds
    DEFAULT_BACKGROUND = "#8883"  #transparent grey that works in both JupyterLab Light/Dark modes

    #: Default color for table borders
    DEFAULT_BORDER_COLOUR = '#c0c0c0'

    #: CSS style for header rows and column.
    HEADER_PROPERTIES = [('background', DEFAULT_BACKGROUND),
                         ('font-weight', '500')]

    #: CSS style for summary content cells.
    SUMMARY_PROPERTIES = HEADER_PROPERTIES

    #: Base styles
    STYLES = [
        {'selector': 'th', 'props': HEADER_PROPERTIES},
        {'selector': 'tr', 'props': [('background', 'none')]},
        {'selector': 'td', 'props': [('text-align', 'right'),
                                     ('min-width', '3em')]},
        {'selector': '*', 'props': [('border-color', DEFAULT_BORDER_COLOUR)]},
    ]

    _NO_INDEX_STYLES = [
        {'selector': '.row_heading', 'props': [('display', 'none')]},
        {'selector': '.blank', 'props': [('display', 'none')]}
    ]    

    #: Default local for formatting functions
    DEFAULT_LOCALE = LOCALE_OBJ

    def __init__(self,
                 data,
                 summary_rows=None,
                 summary_cols=None,
                 formatters=None,
                 replace_all_nans_with=None,
                 show_index=True,
                 *args,
                 **kwargs):

        kwargs['table_styles'] = self.STYLES + kwargs.get('table_styles', [])

        if not show_index:
            kwargs['table_styles'] += self._NO_INDEX_STYLES
            
        self.summary_rows = summary_rows or []
        self.summary_cols = summary_cols or []
        self.formatters = formatters or []
        self.replace_all_nans_with = replace_all_nans_with

        super(PrettyPandas, self).__init__(data, *args, **kwargs)
        
        def default_display_func(x):
            if is_float(x):
                return '{:>.{precision}f}'.format(x, precision=self.precision)
            else:
                return x

        self._display_funcs = defaultdict(lambda: default_display_func)        

    @classmethod
    def set_locale(cls, locale):
        """Set the PrettyPandas default locale."""
        cls.DEFAULT_LOCALE = locale

    def _append_selector(self, selector, *props):
        """Add a CSS selector and style to this Styler."""
        self.table_styles.append({'selector': selector, 'props': props})

    def summary(self, func=np.sum, title='Total', axis=0, **kwargs):
        """Add multiple summary rows or columns to the dataframe.

        Parameters
        ----------
        :param func: Iterable of functions to be used for a summary.
        :param titles: Iterable of titles in the same order as the functions.
        :param axis:
            Same as numpy and pandas axis argument. A value of None will cause
            the summary to be applied to both rows and columns.
        :param kwargs: Keyword arguments passed to all the functions.

        The results of summary can be chained together.
        """
        return self.multi_summary([func], [title], axis, **kwargs)

    def multi_summary(self, funcs, titles, axis=0, subset=None, exclude=None, **kwargs):
        """Add multiple summary rows or columns to the dataframe.

        Parameters
        ----------
        :param funcs: Iterable of functions to be used for a summary.
        :param titles: Iterable of titles in the same order as the functions.
        :param axis:
            Same as numpy and pandas axis argument. A value of None will cause
            the summary to be applied to both rows and columns.
        :param kwargs: Keyword arguments passed to all the functions.
        """
        if axis is None:
            return self.multi_summary(funcs, titles, axis=0, **kwargs)\
                       .multi_summary(funcs, titles, axis=1, **kwargs)

        output = []
        if axis == 0:
            #use df to iterate over rows of the transpose of self.data below
            #(i.e. cols of self.data)
            iter_fn = self.data.iteritems
            summary_names = self.data.columns
        else:
            iter_fn = self.data.iterrows
            summary_names = self.data.index
            
        if exclude is not None and subset is None:
            subset = [n for n in summary_names if n not in exclude]
            
        for f, t in zip(funcs, titles):
            if subset is None:
                #apply returns Series, to_frame converts to DataFrame
                output.append(self.data.apply(f, axis=axis, **kwargs)
                                       .to_frame(t)) 
            elif subset is not None:
                summary_vals = [f(vals, **kwargs) if item_name in subset 
                                else None for item_name, vals in iter_fn()]
                #dataframe with column name t and values summary_vals
                output.append(pd.DataFrame(data = {t: summary_vals}, 
                                           index = summary_names))  

        if axis == 0:
            self.summary_rows += [row.T for row in output]
        elif axis == 1:
            self.summary_cols += output
        else:
            ValueError("Invalid axis selected. Can only use 0, 1, or None.")

        return self

    def total(self, title="Total", **kwargs):
        """Add a total summary to this table.

        :param title: Title to be displayed.
        :param kwargs: Keyword arguments passed to ``numpy.sum``.
        """
        return self.summary(np.sum, title, **kwargs)

    def average(self, title="Average", **kwargs):
        """Add a mean summary to this table.

        :param title: Title to be displayed.
        :param kwargs: Keyword arguments passed to ``numpy.mean``.
        """
        return self.summary(np.average, title, **kwargs)

    def median(self, title="Median", **kwargs):
        """Add a median summary to this table.

        :param title: Title to be displayed.
        :param kwargs: Keyword arguments passed to ``numpy.median``.
        """
        return self.summary(np.median, title, **kwargs)

    def max(self, title="Maximum", **kwargs):
        """Add a maximum summary to this table.

        :param title: Title to be displayed.
        :param kwargs: Keyword arguments passed to ``numpy.max``.
        """
        return self.summary(np.max, title, **kwargs)

    def min(self, title="Minimum", **kwargs):
        """Add a minimum summary to this table.

        :param title: Title to be displayed.
        :param kwargs: Keyword arguments passed to ``numpy.min``.
        """
        return self.summary(np.min, title, **kwargs)

    def as_percent(self, precision=0, **kwargs):
        """Represent subset of dataframe as percentages.

        Parameters:
        -----------
        :param precision: int
            Number of decimal places to round to
        """

        return self._format_cells(PERCENT_FORMATTERS['format_fn'],
                                  precision=precision,
                                  **kwargs)

    @classmethod
    def set_percent_formatter(cls, formatter = 'as_percent_babel'):
        """Set the formatting function used for percentages

        Parameters:
        -----------
        :param formatter str or callable: 
            A string selecting a formatting function from 
            PERCENT_FORMATTERS['formatters'] (current options are 'as_percent_babel'
            or 'as_percent_with_precision'), or a function that can be used for
            percent formatting.
        """        
        PERCENT_FORMATTERS['format_fn'] = \
            PERCENT_FORMATTERS['formatters'].get(formatter, formatter)
            
    def as_currency(self, currency='USD', locale=None, **kwargs):
        """Represent subset of dataframe as currency.

        Parameters:
        -----------
        :param currency: Currency or currency symbol to be used
        :param locale: Locale to be used (e.g. 'en_US')
        """
        add_formatter = partial(self._format_cells,
                                as_currency,
                                currency=currency, 
                                **kwargs)

        if locale is not None:
            return add_formatter(locale=locale)
        else:
            return add_formatter(locale=self.DEFAULT_LOCALE)

    def as_unit(self, unit, precision=None, location='prefix', **kwargs):
        """Represent subset of dataframe as a special unit.

        Parameters:
        -----------
        :param unit: string representing unit to be used.
        :param precision: int
            Number of decimal places to round to
        :param location: 'prefix' or 'suffix' indicating where the currency symbol
            should be.
        """
        precision = self.precision if precision is None else precision

        return self._format_cells(as_unit,
                                  precision=precision,
                                  unit=unit,
                                  location=location, 
                                  **kwargs)

    def as_number(self, *args, **kwargs):
        """Shortcut for as_unit('', ...)"""
        return self.as_unit('', *args, **kwargs)
        
    def as_money(self,
                 precision=None,
                 currency='$',
                 location='prefix', 
                 **kwargs):
        """[DEPRECATED] Represent subset of dataframe as currency.

        Parameters:
        -----------
        :param precision: int
            Number of decimal places to round to
        :param currency: Currency string
        :param location: 'prefix' or 'suffix' indicating where the currency
            symbol should be.
        """

        precision = self.precision if precision is None else precision

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self._format_cells(as_money,
                                      currency=currency,
                                      precision=precision,
                                      location=location, 
                                      **kwargs)

    def _format_cells(self, func, subset=None, exclude=None, axis='columns', **kwargs):
        """Add formatting function to cells."""

        if self.replace_all_nans_with is not None \
            and 'replace_nan_with' not in kwargs:
            kwargs['replace_nan_with'] = self.replace_all_nans_with

        # Create function closure for formatting operation
        def fn(*args):
            return func(*args, **kwargs)

        self.formatters.append(Formatter(subset=subset, exclude=exclude, axis=axis, function=fn))
        return self

    def _apply_formatters(self):
        """Apply all added formatting."""
        for subset, exclude, axis, function in self.formatters:
            if axis == 'columns':
                index = self.data.columns
            elif axis == 'rows':
                index = self.data.index
            else:
                raise ValueError("axis must be one of 'columns' or 'rows'")
            if subset is None:
                subset = index
            else:
                subset = [s for s in subset if s in index]
                if not subset:
                    continue
                
            if exclude is not None:
                subset = [s for s in subset if s not in exclude]
            
            if axis == 'columns':
                self.data.loc[:, subset] = self.data.loc[:, subset].applymap(function)
            else:
                self.data.loc[subset, :] = self.data.loc[subset, :].applymap(function)
        return self

    def _apply_summaries(self):
        """Add all summary rows and columns."""
        colnames = list(self.data.columns)
        summary_colnames = [series.columns[0] for series in self.summary_cols]
        summary_rownames = [series.index[0] for series in self.summary_rows]

        # preserve index&columns names
        index_names = self.data.index.names
        columns_names = self.data.columns.names
        
        rows, cols = self.data.shape
        ix_rows = self.data.index.size
        ix_cols = len(index_names)

        # Add summary rows and columns
        self.data = pd.concat([self.data] + self.summary_cols,
                              axis=1,
                              ignore_index=False)
        self.data = pd.concat([self.data] + self.summary_rows,
                              axis=0,
                              ignore_index=False)

        # Update CSS styles
        for i, _ in enumerate(self.summary_rows):
            index = rows + i + 1
            self._append_selector('tr:nth-child({})'.format(index),
                                  *self.SUMMARY_PROPERTIES)

        for i, _ in enumerate(self.summary_cols):
            index = cols + ix_cols + i + 1
            self._append_selector('td:nth-child({})'.format(index),
                                  *self.SUMMARY_PROPERTIES)

        # Sort column names
        self.data = self.data[colnames + summary_colnames]

        # Fix shared summary cells to be empty
        for row, col in product(summary_rownames, summary_colnames):
            self.data.loc[row, col] = ''
            
        #replace index&columns names which can be erased due to concat
        self.data.index.names = index_names
        self.data.columns.names = columns_names

        return self

    def get_formatted_df(self, as_html = False):
        """Apply styles and formats before rendering to a dataframe."""
        data = self.data.copy()

        self._apply_summaries()
        self._apply_formatters()
        formatted_df = self.data
        
        # underlying Styler relies on these (created at __init__), but they need to be updated based on summaries applied
        self.index = self.data.index  
        self.columns = self.data.columns
        result = super(self.__class__, self)._translate()

        # Revert changes to inner data
        self.data = data
        
        if as_html:
            return result
        else:
            if self.replace_all_nans_with is not None:
                for col in formatted_df:
                    formatted_df.loc[formatted_df[col].isnull(), col] = self.replace_all_nans_with
            return formatted_df

    def _translate(self):
        """Apply styles and formats before rendering."""
        result = self.get_formatted_df(as_html = True)

        head = result['head']
        if len(head) == 2:
            #try to merge index name column headers with column index
            merge_headers = True
            merged = []
            for col0, col1 in zip(head[0], head[1]):
                if 'blank' not in col0['class'] and 'blank' in col1['class']:
                    merged.append(col0)
                elif 'blank' in col0['class'] and 'blank' not in col1['class']:
                    merged.append(col1)
                else:
                    merge_headers = False
                    break

            if merge_headers:
                result['head'] = [merged]
        
        if self.replace_all_nans_with is not None:
            for row in result['body']:
                for cell in row:
                    v = cell['value']
                    if isinstance(v, Number) and np.isnan(v):
                        cell['display_value'] = self.replace_all_nans_with 
        return result